import json
import os
import re
import logging
from typing import Dict, List, Set, Tuple, Optional
from collections import Counter
import openai
from utils import (
    load_env_file, 
    get_env, 
    is_valid_api_key, 
    normalize_doc_type, 
    update_readme_report_block
)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants (Relative to assessment_solution directory)
DATASET_PATH = "../nc_records_assessment.jsonl"
MAPPING_OUTPUT_PATH = "outputs/doc_type_mapping.json"
README_PATH = "README.md"
CERTAINTY_A = "HIGH"
CERTAINTY_B = ["HIGH", "MEDIUM"]
FALLBACK_CATEGORY = "MISC"
TOKENS_PER_MILLION = 1_000_000
PARETO_THRESHOLD = 0.95 # Target 95% record coverage for strategic sampling

CATEGORIES = [
    "SALE_DEED", "MORTGAGE", "DEED_OF_TRUST", "RELEASE", 
    "LIEN", "PLAT", "EASEMENT", "LEASE"
]
# MISC is the 9th category, used as fallback

PROTOTYPES = {
    "SALE_DEED": ["deed", "warranty deed", "quitclaim", "grant deed", "conveyance"],
    "MORTGAGE": ["mortgage", "mtg"],
    "DEED_OF_TRUST": ["deed of trust", "dot", "trust deed"],
    "RELEASE": ["release", "satisfaction", "reconveyance", "discharge"],
    "LIEN": ["lien", "claim of lien", "mechanics lien", "ucc"],
    "PLAT": ["plat", "map", "survey"],
    "EASEMENT": ["easement", "right of way", "row", "r/w"],
    "LEASE": ["lease", "memorandum of lease"]
}

class DocTypeClassifier:
    def __init__(self):
        load_env_file()
        self.api_key = get_env("OPENAI_API_KEY")
        
        # Validate API Key Format (sk-...)
        if is_valid_api_key(self.api_key):
            if not self.api_key.startswith("sk-"):
                logger.warning("OPENAI_API_KEY does not start with 'sk-'. It may be invalid.")
            self.client = openai.OpenAI(api_key=self.api_key)
            logger.info("LLM enabled: true")
        else:
            self.client = None
            logger.info("LLM enabled: false")
            if self.api_key:
                logger.warning("OPENAI_API_KEY found but appears to be a placeholder or invalid.")
        
        # Validate CATEGORIES/PROTOTYPES consistency
        self._validate_config()

        # Pass 1 Rules (Regex)
        self.rules = {
            "SALE_DEED": [
                r"\bWARRANTY\s+DEED\b", 
                r"\bQUIT\s*CLAIM\b", 
                r"\bGRANT\s+DEED\b", 
                r"\bDEED\b(?!\s+OF\s+TRUST\b)", 
                r"\bCONVEYANCE\b"
            ],
            "MORTGAGE": [
                r"\bMORTGAGE\b", 
                r"\bMTG\b",
                r"^MTGE$" # Added from mapping
            ],
            "DEED_OF_TRUST": [
                r"\bDEED\s+OF\s+TRUST\b", 
                r"\bDOT\b", 
                r"\bTRUST\s+DEED\b",
                r"^(?:DT|D\s*T|D/T)$",
                r"^D\s+OF\s+T$",
                r"^D-TR$" # Added from mapping
            ],
            "RELEASE": [
                r"\bRELEASE\b", 
                r"\bSATISFACTION\b", 
                r"\bRECONVEYANCE\b", 
                r"\bDISCHARGE\b",
                r"^(?:SAT)$",
                r"\bSAT\b",
                r"^REL\s+D$",
                r"^D-REL$", # Added from mapping
                r"^C-SAT$", # Added from mapping
                r"^N-SAT$"  # Added from mapping
            ],
            "LIEN": [r"\bLIEN\b", r"\bUCC\b", r"\bMECHANIC\b"],
            "PLAT": [
                r"\bPLAT\b", 
                r"\bSURVEY\b",
                r"^(?:MAP|MAP/R)$",
                r"\bMAP\b"
            ],
            "EASEMENT": [
                r"\bEASEMENT\b", 
                r"\bRIGHT\s+OF\s+WAY\b", 
                r"\bROW\b", 
                r"(?:^|\s)R/W(?:\s|$)",
                r"^ESMT$",
                r"^EASE$", # Added from mapping
                r"^R-WAY$"  # Added from mapping
            ],
            "LEASE": [r"\bLEASE\b"]
        }
        
        # Pre-compile regex patterns for performance
        self.compiled_rules = {
            cat: [re.compile(p) for p in patterns] 
            for cat, patterns in self.rules.items()
        }

        # Usage Tracking
        self.usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "calls": 0
        }
        # GPT-4o-mini pricing as of Jan 2025 (approximate)
        self.PRICE_PER_1M_PROMPT = 0.15
        self.PRICE_PER_1M_COMPLETION = 0.60

    def _validate_config(self):
        """Ensure CATEGORIES and PROTOTYPES are in sync."""
        for cat in CATEGORIES:
            if cat not in PROTOTYPES:
                logger.warning(f"Category '{cat}' missing from PROTOTYPES.")
        for cat in PROTOTYPES:
            if cat not in CATEGORIES:
                logger.warning(f"Prototype category '{cat}' not in CATEGORIES list.")

    def extract_unique_doc_types(self, file_path: str) -> Tuple[Dict[str, int], int]:
        """Step 0: Extract unique doc_type values and frequencies."""
        logger.info(f"Extracting unique doc_types from {file_path}...")
        counts = Counter()
        total_records = 0
        
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                total_records += 1
                try:
                    record = json.loads(line)
                    doc_type = record.get("doc_type")
                    if doc_type is None:
                        doc_type = ""
                    counts[doc_type] += 1
                except json.JSONDecodeError:
                    logger.error(f"Malformed JSON on line {total_records}")
                    counts[""] += 1
        
        logger.info(f"Found {len(counts)} unique doc_types across {total_records} records.")
        return dict(counts), total_records

    def pass1_rules(self, unique_doc_types: List[str]) -> Tuple[Dict[str, str], List[str]]:
        """Step 1: High-precision regex rules with ambiguity detection."""
        logger.info("Running Pass 1: Regex Rules...")
        resolved = {}
        unresolved = []
        
        for raw_type in unique_doc_types:
            norm = normalize_doc_type(raw_type)
            if not norm:
                unresolved.append(raw_type)
                continue
                
            matches = []
            for category, patterns in self.compiled_rules.items():
                if any(pattern.search(norm) for pattern in patterns):
                    matches.append(category)
            
            unique_matches = list(set(matches))
            
            if len(unique_matches) == 1:
                resolved[raw_type] = unique_matches[0]
            else:
                # Ambiguous (0 or >1 matches)
                unresolved.append(raw_type)
        
        logger.info(f"Pass 1 resolved {len(resolved)} types, {len(unresolved)} remaining.")
        return resolved, unresolved

    def call_llm(self, doc_types: List[str], use_prototypes: bool = False) -> List[Dict]:
        """Helper to call LLM for a batch of doc_types with retry logic."""
        if not self.client:
            return []

        categories_str = ", ".join(CATEGORIES)
        
        system_prompt = (
            "You are a legal document classifier. Classify the following document types "
            f"into exactly one of these categories: {categories_str}, or 'MISC'. "
            "Return a JSON object with a 'results' key containing a list of objects: "
            "[{\"doc_type\": \"...\", \"category\": \"...\", \"certainty\": \"HIGH/MEDIUM/LOW\", \"reason\": \"...\"}]. "
            "\n\nCERTAINTY RUBRIC:"
            "\n- HIGH: Clear direct match."
            "\n- MEDIUM: Plausible but not fully explicit."
            "\n- LOW: Truly unclear. Avoid LOW unless necessary."
            "\n\nCRITICAL CONSTRAINTS:"
            "\n1. Return doc_type EXACTLY as provided (verbatim)."
            f"\n2. category MUST be one of: {categories_str}, or 'MISC'."
            "\n3. certainty MUST be: 'HIGH', 'MEDIUM', or 'LOW'."
            "\n4. reason MUST be short (3-7 words)."
            "\n5. Output JSON object only."
        )
        
        if use_prototypes:
            proto_str = "\n".join([f"{cat}: {', '.join(examples)}" for cat, examples in PROTOTYPES.items()])
            system_prompt += f"\n\nUse these prototypes for reference:\n{proto_str}"

        user_prompt = f"Classify: {json.dumps(doc_types)}"
        
        for attempt in range(2): # Simple retry for malformed JSON
            try:
                response = self.client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0
                )
                
                if hasattr(response, 'usage') and response.usage:
                    self.usage["prompt_tokens"] += response.usage.prompt_tokens
                    self.usage["completion_tokens"] += response.usage.completion_tokens
                self.usage["calls"] += 1

                content = response.choices[0].message.content
                data = json.loads(content)
                return data.get("results", [])
            except json.JSONDecodeError:
                logger.warning(f"Malformed JSON on attempt {attempt + 1}. Retrying...")
                continue
            except Exception as e:
                logger.error(f"LLM call failed: {e}")
                break
        return []

    def pass2_llm(self, unresolved: List[str], accepted_certainty: List[str], use_prototypes: bool = False, batch_size: int = 40) -> Tuple[Dict[str, str], List[str]]:
        """Step 2: LLM classification (Pass 2a or 2b). Optimized batch size for accuracy."""
        label = "Pass 2b (Prototypes)" if use_prototypes else "Pass 2a (Batch)"
        logger.info(f"Running {label}...")
        resolved = {}
        still_unresolved = []
        
        for i in range(0, len(unresolved), batch_size):
            batch = unresolved[i:i+batch_size]
            results = self.call_llm(batch, use_prototypes=use_prototypes)
            
            # Map results back with verbatim and normalized fallbacks
            batch_results = {}
            normalized_batch_results = {}
            
            for res in results:
                raw_dt = res.get("doc_type")
                if raw_dt:
                    batch_results[raw_dt] = res
                    normalized_batch_results[normalize_doc_type(raw_dt)] = res
            
            for raw_type in batch:
                # 1. Try verbatim match
                res = batch_results.get(raw_type)
                
                # 2. Try normalized fallback if verbatim fails
                if not res:
                    res = normalized_batch_results.get(normalize_doc_type(raw_type))
                
                valid_categories = CATEGORIES + [FALLBACK_CATEGORY]
                if res and res.get("category") in valid_categories and res.get("certainty") in accepted_certainty:
                    resolved[raw_type] = res["category"]
                else:
                    still_unresolved.append(raw_type)
                    
        logger.info(f"{label} resolved {len(resolved)} types, {len(still_unresolved)} remaining.")
        return resolved, still_unresolved

    def run_pipeline(self):
        # Step 0
        counts, total_records = self.extract_unique_doc_types(DATASET_PATH)
        unique_types = list(counts.keys())
        
        # Step 1
        resolved_p1, unresolved_p1 = self.pass1_rules(unique_types)
        
        # Step 1.5: Identify top unresolved by frequency for README
        top_unresolved = sorted(
            [{"doc_type": ut, "count": counts[ut]} for ut in unresolved_p1],
            key=lambda x: x["count"],
            reverse=True
        )
        top_15 = top_unresolved[:15]

        # Step 2: LLM Passes
        resolved_p2a = {}
        resolved_p2b = {}
        
        if self.client:
            # Pareto-based strategic sampling: cover 95% of unresolved records
            unresolved_with_counts = sorted(
                [(ut, counts.get(ut, 0)) for ut in unresolved_p1],
                key=lambda x: x[1],
                reverse=True
            )
            
            total_unresolved_records = sum(c for _, c in unresolved_with_counts)
            
            if total_unresolved_records == 0:
                logger.info("No unresolved records remain after Pass 1. Skipping LLM passes.")
                strategic_sample = []
                low_freq_remainder = []
            else:
                cumulative = 0
                strategic_sample = []
                
                for ut, count in unresolved_with_counts:
                    strategic_sample.append(ut)
                    cumulative += count
                    if cumulative >= PARETO_THRESHOLD * total_unresolved_records:
                        break
                
                low_freq_remainder = [ut for ut, _ in unresolved_with_counts if ut not in strategic_sample]
            
            if low_freq_remainder:
                skipped_records = sum(counts.get(ut, 0) for ut in low_freq_remainder)
                logger.info(f"Strategic sampling: skipping {len(low_freq_remainder)} low-frequency types, "
                            f"representing {skipped_records} records ({skipped_records/total_records:.1%} of dataset).")

            if strategic_sample:
                # Step 2a
                resolved_p2a, unresolved_p2a = self.pass2_llm(strategic_sample, [CERTAINTY_A], use_prototypes=False)
                
                # Step 2b
                resolved_p2b, unresolved_p2b = self.pass2_llm(unresolved_p2a, CERTAINTY_B, use_prototypes=True)
                
                # Log unclassified strategic items
                unclassified_strategic = [rt for rt in strategic_sample if rt not in resolved_p2a and rt not in resolved_p2b]
                if unclassified_strategic:
                    logger.info(f"{len(unclassified_strategic)} strategic sample types remained unclassified after LLM passes.")
        else:
            logger.info("Skipping LLM passes; missing or placeholder API key.")
        
        # Final Assembly
        final_mapping = {}
        for rt in unique_types:
            if rt in resolved_p1:
                final_mapping[rt] = resolved_p1[rt]
            elif rt in resolved_p2a:
                final_mapping[rt] = resolved_p2a[rt]
            elif rt in resolved_p2b:
                final_mapping[rt] = resolved_p2b[rt]
            else:
                final_mapping[rt] = "MISC"
        
        # Save output
        with open(MAPPING_OUTPUT_PATH, 'w', encoding='utf-8') as f:
            json.dump(final_mapping, f, indent=2)
        logger.info(f"Mapping saved to {MAPPING_OUTPUT_PATH}")
        
        # Calculate Metrics
        self.generate_report(counts, total_records, resolved_p1, resolved_p2a, resolved_p2b, final_mapping, top_15)

    def generate_report(self, counts, total_records, p1, p2a, p2b, final, top_unresolved):
        unique_count = len(counts)
        p1_count = len(p1)
        p2a_count = len(p2a)
        p2b_count = len(p2b)
        misc_count = sum(1 for v in final.values() if v == "MISC")
        
        # Frequency-weighted
        def get_weighted(mapping_subset):
            return sum(counts[rt] for rt in mapping_subset if rt in counts)
            
        p1_weighted = get_weighted(p1)
        p2a_weighted = get_weighted(p2a)
        p2b_weighted = get_weighted(p2b)
        misc_weighted = sum(counts[rt] for rt, cat in final.items() if cat == "MISC")
        
        # Cost Calculation
        cost = (self.usage["prompt_tokens"] / TOKENS_PER_MILLION * self.PRICE_PER_1M_PROMPT) + \
               (self.usage["completion_tokens"] / TOKENS_PER_MILLION * self.PRICE_PER_1M_COMPLETION)

        # Format top unresolved for README
        top_unresolved_md = "\n".join([f"- `{item['doc_type']}` ({item['count']} records)" for item in top_unresolved])

        report_content = f"""
### 📊 Pipeline Metrics

#### Coverage (Unique Doc Types)
- **Non-MISC types**: {unique_count - misc_count} / {unique_count} ({ (unique_count - misc_count)/unique_count:.1%})
- **MISC types**: {misc_count} / {unique_count} ({misc_count/unique_count:.1%})
- **Breakdown by pass**:
    - Resolved by Pass 1 (Rules): {p1_count} ({p1_count/unique_count:.1%})
    - Resolved by Pass 2a (LLM): {p2a_count} ({p2a_count/unique_count:.1%})
    - Resolved by Pass 2b (LLM+Proto): {p2b_count} ({p2b_count/unique_count:.1%})

#### Coverage (All Records — weighted)
- **Non-MISC records**: {total_records - misc_weighted:,} / {total_records:,} ({(total_records - misc_weighted)/total_records:.1%})
- **MISC records**: {misc_weighted:,} / {total_records:,} ({misc_weighted/total_records:.1%})

#### LLM Usage & Cost
- **Total LLM Calls**: {self.usage['calls']}
- **Tokens**: {self.usage['prompt_tokens']} prompt / {self.usage['completion_tokens']} completion
- **Estimated Cost**: ${cost:.4f}

#### Top Unresolved (After Pass 1)
{top_unresolved_md}
"""
        # Stable README update using helper from utils.py
        update_readme_report_block(
            readme_path=README_PATH,
            start_marker="<!-- REPORT_START -->",
            end_marker="<!-- REPORT_END -->",
            report_markdown=report_content
        )

if __name__ == "__main__":
    classifier = DocTypeClassifier()
    classifier.run_pipeline()
