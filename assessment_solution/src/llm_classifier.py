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
        
        if is_valid_api_key(self.api_key):
            self.client = openai.OpenAI(api_key=self.api_key)
            logger.info("LLM enabled: true")
        else:
            self.client = None
            logger.info("LLM enabled: false")
            if self.api_key:
                logger.warning("OPENAI_API_KEY found but appears to be a placeholder or invalid.")
        
        # Pass 1 Rules (Regex)
        self.rules = {
            "SALE_DEED": [
                r"\bWARRANTY\s+DEED\b", 
                r"\bQUIT\s*CLAIM\b", 
                r"\bGRANT\s+DEED\b", 
                r"\bDEED\b(?!\s+OF\s+TRUST\b)", # Negative lookahead to avoid DOT ambiguity
                r"\bCONVEYANCE\b"
            ],
            "MORTGAGE": [r"\bMORTGAGE\b", r"\bMTG\b"],
            "DEED_OF_TRUST": [
                r"\bDEED\s+OF\s+TRUST\b", 
                r"\bDOT\b", 
                r"\bTRUST\s+DEED\b",
                r"^(?:DT|D\s*T|D/T)$" # High-impact abbreviations
            ],
            "RELEASE": [
                r"\bRELEASE\b", 
                r"\bSATISFACTION\b", 
                r"\bRECONVEYANCE\b", 
                r"\bDISCHARGE\b",
                r"^(?:SAT)$", # Exact match for SAT
                r"\bSAT\b"
            ],
            "LIEN": [r"\bLIEN\b", r"\bUCC\b", r"\bMECHANIC\b"],
            "PLAT": [
                r"\bPLAT\b", 
                r"\bSURVEY\b",
                r"^(?:MAP|MAP/R)$", # Exact match for MAP/R
                r"\bMAP\b"
            ],
            "EASEMENT": [r"\bEASEMENT\b", r"\bRIGHT\s+OF\s+WAY\b", r"\bROW\b", r"(?:^|\s)R/W(?:\s|$)"],
            "LEASE": [r"\bLEASE\b"]
        }

        # Usage Tracking
        self.usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "calls": 0
        }
        # GPT-4o-mini pricing as of Jan 2026 (approximate)
        self.PRICE_PER_1M_PROMPT = 0.15
        self.PRICE_PER_1M_COMPLETION = 0.60

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

    def normalize(self, text: str) -> str:
        if not text:
            return ""
        return text.strip().upper()

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
            for category, patterns in self.rules.items():
                for pattern in patterns:
                    if re.search(pattern, norm):
                        matches.append(category)
                        break # Move to next category
            
            unique_matches = list(set(matches))
            
            if len(unique_matches) == 1:
                resolved[raw_type] = unique_matches[0]
            else:
                # Ambiguous (0 or >1 matches)
                unresolved.append(raw_type)
        
        logger.info(f"Pass 1 resolved {len(resolved)} types, {len(unresolved)} remaining.")
        return resolved, unresolved

    def call_llm(self, doc_types: List[str], use_prototypes: bool = False) -> List[Dict]:
        """Helper to call LLM for a batch of doc_types."""
        if not self.client:
            # Silent return as the pipeline already logs skipping info
            return []

        categories_str = ", ".join(CATEGORIES)
        
        system_prompt = (
            "You are a legal document classifier. Classify the following document types "
            f"into exactly one of these categories: {categories_str}, or 'MISC'. "
            "Return a JSON object with a 'results' key containing a list of objects: "
            "[{\"doc_type\": \"...\", \"category\": \"...\", \"certainty\": \"HIGH/MEDIUM/LOW\", \"reason\": \"...\"}]. "
            "\n\nCERTAINTY RUBRIC:"
            "\n- HIGH: Clear direct match to a category or prototype."
            "\n- MEDIUM: Plausible classification but not fully explicit."
            "\n- LOW: Truly unclear or insufficient information. Avoid LOW unless necessary."
            "\n\nCRITICAL CONSTRAINTS:"
            "\n1. Return doc_type EXACTLY as provided (verbatim). Do not modify whitespace, casing, or punctuation."
            f"\n2. category MUST be exactly one of: {categories_str}, or 'MISC'."
            "\n3. certainty MUST be exactly one of: 'HIGH', 'MEDIUM', or 'LOW'."
            "\n4. reason MUST be a short explanation (3-7 words)."
            "\n5. Output JSON object only, no markdown or prose."
        )
        
        if use_prototypes:
            proto_str = "\n".join([f"{cat}: {', '.join(examples)}" for cat, examples in PROTOTYPES.items()])
            system_prompt += f"\n\nUse these prototypes for reference:\n{proto_str}"

        user_prompt = f"Classify these document types: {json.dumps(doc_types)}"
        
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
            
            # Track Usage
            if hasattr(response, 'usage') and response.usage:
                self.usage["prompt_tokens"] += response.usage.prompt_tokens
                self.usage["completion_tokens"] += response.usage.completion_tokens
            self.usage["calls"] += 1

            content = response.choices[0].message.content
            data = json.loads(content)
            return data.get("results", [])
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return []

    def pass2_llm(self, unresolved: List[str], accepted_certainty: List[str], use_prototypes: bool = False, batch_size: int = 50) -> Tuple[Dict[str, str], List[str]]:
        """Step 2: LLM classification (Pass 2a or 2b)."""
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
                
                if res and res.get("category") in CATEGORIES and res.get("certainty") in accepted_certainty:
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
        top_30 = top_unresolved[:30]

        # Step 2: LLM Passes
        resolved_p2a = {}
        resolved_p2b = {}
        
        if self.client:
            # Step 2a
            resolved_p2a, unresolved_p2a = self.pass2_llm(unresolved_p1, [CERTAINTY_A], use_prototypes=False)
            
            # Step 2b
            resolved_p2b, unresolved_p2b = self.pass2_llm(unresolved_p2a, CERTAINTY_B, use_prototypes=True)
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
        self.generate_report(counts, total_records, resolved_p1, resolved_p2a, resolved_p2b, final_mapping, top_30[:15])

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
        cost = (self.usage["prompt_tokens"] / 1_000_000 * self.PRICE_PER_1M_PROMPT) + \
               (self.usage["completion_tokens"] / 1_000_000 * self.PRICE_PER_1M_COMPLETION)

        # Format top unresolved for README
        top_unresolved_md = "\n".join([f"- `{item['doc_type']}` ({item['count']} records)" for item in top_unresolved])

        report_content = f"""
### ✅ Task 3: Document Type Classification (COMPLETE)
**Script:** `src/llm_classifier.py`  
**Output:** `outputs/doc_type_mapping.json`  
**Objective:** Standardize messy `doc_type` values into 9 canonical categories using a multi-pass pipeline (Regex + LLM).

#### 📋 Task 3: Methodology & Report

## Coverage Metrics (Unique Doc Types — unweighted)
*These percentages are out of the {unique_count} unique doc_type strings found in the dataset. Many rare/long-tail types may remain MISC.*
- **Non-MISC types**: {unique_count - misc_count} / {unique_count} ({ (unique_count - misc_count)/unique_count:.1%})
- **MISC types**: {misc_count} / {unique_count} ({misc_count/unique_count:.1%})
- Breakdown by pass:
    - Resolved by Pass 1 (Rules): {p1_count} ({p1_count/unique_count:.1%})
    - Resolved by Pass 2a (LLM): {p2a_count} ({p2a_count/unique_count:.1%})
    - Resolved by Pass 2b (LLM+Proto): {p2b_count} ({p2b_count/unique_count:.1%})

## Coverage Metrics (All Records — frequency-weighted by occurrence)
*These percentages are out of the {total_records:,} total records. A small set of very common doc_type values can cover most records even if many rare types are MISC.*
- **Non-MISC records**: {total_records - misc_weighted} / {total_records} ({(p1_weighted + p2a_weighted + p2b_weighted)/total_records:.1%})
- **MISC records**: {misc_weighted} / {total_records} ({misc_weighted/total_records:.1%})

> **Note on Metrics**: It’s normal for MISC to be high by unique types but low by records because MISC often contains many low-frequency (long-tail) values that have minimal impact on overall dataset coverage.

## LLM Usage & Estimated Cost
- Total LLM Calls: {self.usage['calls']}
- Prompt Tokens: {self.usage['prompt_tokens']}
- Completion Tokens: {self.usage['completion_tokens']}
- Estimated Cost: ${cost:.4f} (using assumed GPT-4o-mini rates; verify current pricing)

## Top Unresolved by Frequency (After Pass 1)
{top_unresolved_md}

## Methodology
1. **Pass 1 (High-Precision Rules)**: Regex-based matching. Ambiguous matches (multiple categories) are deferred.
2. **Pass 2a (LLM Batch)**: GPT-4o-mini classification accepting only certainty='{CERTAINTY_A}'.
3. **Pass 2b (LLM Calibration)**: GPT-4o-mini with canonical prototypes accepting certainty in {CERTAINTY_B}.
4. **Fallback**: Anything below thresholds or invalid is mapped to MISC.
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

