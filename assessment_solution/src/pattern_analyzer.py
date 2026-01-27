"""
Pattern Analyzer - County Records Analysis

This module analyzes patterns in North Carolina county records data,
extracting instrument number formats, book/page patterns, date ranges,
and document type distributions across 13 counties.
"""

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class PatternAnalyzer:
    """Analyzes patterns in county records data."""
    
    # Configuration constants
    ZERO_PADDED_MERGE_THRESHOLD = 0.05  # Merge zero-padded into numeric if < 5% of records
    OTHER_BUCKET_THRESHOLD_PCT = 0.02   # Include pattern in top-N if > 2% of records
    OTHER_BUCKET_THRESHOLD_MIN = 100    # Or if pattern has at least 100 records
    MAX_EXAMPLES_PER_FAMILY = 20        # Examples collected per family for regex generation
    MAX_ANOMALY_EXAMPLES = 5            # Maximum anomaly examples to store per type
    TOP_N_PATTERNS = 5                  # Always include top N patterns per county

    def __init__(self):
        """Initialize data structures for pattern analysis."""
        # Per-county data structures
        self.data = defaultdict(lambda: {
            "record_count": 0,
            "instrument": {"families": Counter(), "examples": {}, "values": {}},
            "book": {
                "families": Counter(),
                "examples": {},
                "values": {},
                "numeric_values": [],
                "numeric_values_by_family": defaultdict(list)
            },
            "page": {
                "families": Counter(),
                "examples": {},
                "values": {},
                "numeric_values": [],
                "numeric_values_by_family": defaultdict(list)
            },
            "dates": {"min": None, "max": None},
            "anomalies": {
                "future_date": [],
                "very_old_date": [],
                "null_date": [],
                "unparseable_date": []
            },
            "anomaly_counts": {
                "future_date": 0,
                "very_old_date": 0,
                "null_date": 0,
                "unparseable_date": 0
            },
            "doc_types": Counter(),
            "type_to_category": defaultdict(Counter)
        })

    def classify_instrument(self, value: Any) -> str:
        """
        Classify instrument number with deterministic precedence.
        
        Priority order (no overlaps):
        1. null_value
        2. bp_prefixed
        3. year_hyphen (19XX-digits or 20XX-digits, digits only after hyphen)
        4. hyphenated (non-year)
        5. year_prefixed (19XX/20XX digits, digits only, no hyphen)
        6. pure_numeric
        7. alphanumeric
        8. other
        
        Note: year_hyphen and year_prefixed use STRICT format interpretation:
        - Must be digits-only after the year prefix
        - Values like "20240091879C" (year + digits + letter) are NOT year_prefixed
        - They fall into alphanumeric or other based on remaining rules
        """
        if value is None or value == "":
            return "null_value"
        
        value_str = str(value).strip()
        if not value_str:
            return "null_value"
        
        # bp_prefixed (synthetic IDs)
        if value_str.startswith("bp"):
            return "bp_prefixed"
        
        # year_hyphen (e.g., 2023-0012345) - STRICT: digits only after hyphen
        if re.match(r"^(19|20)\d{2}-\d+$", value_str):
            return "year_hyphen"
        
        # hyphenated (non-year)
        if "-" in value_str:
            return "hyphenated"
        
        # year_prefixed (no hyphen) - STRICT: digits only, length > 4
        if re.match(r"^(19|20)\d{2}\d+$", value_str) and len(value_str) > 4:
            return "year_prefixed"
        
        # pure_numeric
        if value_str.isdigit():
            return "pure_numeric"
        
        # alphanumeric (contains letters, not bp)
        if re.match(r"^[a-zA-Z0-9]+$", value_str):
            return "alphanumeric"
        
        return "other"

    def classify_book_page(self, value: Any) -> Tuple[str, Optional[int]]:
        """
        Classify book/page number.
        
        Returns (family, numeric_value)
        """
        if value is None or value == "":
            return ("null_value", None)
        
        value_str = str(value).strip()
        if not value_str:
            return ("null_value", None)
        
        # Check if all digits
        if value_str.isdigit():
            numeric_val = int(value_str)
            # zero_padded_numeric (starts with 0 and length > 1)
            if value_str[0] == "0" and len(value_str) > 1:
                return ("zero_padded_numeric", numeric_val)
            # numeric
            return ("numeric", numeric_val)
        
        # alphanumeric
        return ("alphanumeric", None)

    def track_date(self, county: str, date_value: Any, inst_num: str):
        """
        Parse date, track min/max, detect anomalies.
        
        Anomaly types:
        - future_date: date > today (dynamic check)
        - very_old_date: date < 1900-01-01 (heuristic)
        - null_date: date is null
        - unparseable_date: date present but cannot parse
        
        Note: anomaly_counts tracks TOTAL occurrences, examples are capped at 5
        """
        county_data = self.data[county]
        
        # Handle null dates
        if date_value is None or date_value == "":
            county_data["anomaly_counts"]["null_date"] += 1
            if len(county_data["anomalies"]["null_date"]) < self.MAX_ANOMALY_EXAMPLES:
                county_data["anomalies"]["null_date"].append({
                    "date": None,
                    "instrument_number": inst_num
                })
            return
        
        # Try to parse date
        try:
            date_str = str(date_value).strip()
            # Try ISO format first
            if "T" in date_str:
                date_obj = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            else:
                date_obj = datetime.fromisoformat(date_str)
            
            date_only = date_obj.date()
            
            # Track min/max
            if county_data["dates"]["min"] is None or date_only < county_data["dates"]["min"]:
                county_data["dates"]["min"] = date_only
            if county_data["dates"]["max"] is None or date_only > county_data["dates"]["max"]:
                county_data["dates"]["max"] = date_only
            
            # Check anomalies
            today = datetime.now().date()  # Dynamic check (runtime)
            
            # Future date check: any date after today's date at runtime
            if date_only > today:
                county_data["anomaly_counts"]["future_date"] += 1
                if len(county_data["anomalies"]["future_date"]) < self.MAX_ANOMALY_EXAMPLES:
                    county_data["anomalies"]["future_date"].append({
                        "date": date_str,
                        "instrument_number": inst_num
                    })
            
            # Very old date check: before 1900-01-01
            # Conservative heuristic as prompt does not define threshold
            if date_only < datetime(1900, 1, 1).date():
                county_data["anomaly_counts"]["very_old_date"] += 1
                if len(county_data["anomalies"]["very_old_date"]) < self.MAX_ANOMALY_EXAMPLES:
                    county_data["anomalies"]["very_old_date"].append({
                        "date": date_str,
                        "instrument_number": inst_num
                    })
        
        except (ValueError, AttributeError) as e:
            # Unparseable date
            county_data["anomaly_counts"]["unparseable_date"] += 1
            if len(county_data["anomalies"]["unparseable_date"]) < self.MAX_ANOMALY_EXAMPLES:
                county_data["anomalies"]["unparseable_date"].append({
                    "date": str(date_value),
                    "instrument_number": inst_num
                })

    def _process_book_page_field(self, county_data: Dict, field_name: str, value: Any):
        """
        Process a book or page field value.
        
        Args:
            county_data: County data dictionary
            field_name: "book" or "page"
            value: Field value to process
        """
        family, numeric_val = self.classify_book_page(value)
        field_data = county_data[field_name]
        
        # Count family occurrence
        field_data["families"][family] += 1
        
        # Store first example for each family
        if family not in field_data["examples"]:
            field_data["examples"][family] = str(value) if value is not None else None
            field_data["values"][family] = []
        
        # Collect examples for regex generation (capped at MAX_EXAMPLES_PER_FAMILY)
        if len(field_data["values"][family]) < self.MAX_EXAMPLES_PER_FAMILY:
            if value is not None:
                field_data["values"][family].append(str(value))
        
        # Track numeric values (both overall and per-family)
        if numeric_val is not None:
            field_data["numeric_values"].append(numeric_val)
            field_data["numeric_values_by_family"][family].append(numeric_val)

    def process_record(self, record: Dict[str, Any]):
        """Process a single JSON record."""
        county = record.get("county")
        if not county:
            return
        
        county_data = self.data[county]
        county_data["record_count"] += 1
        
        # Process instrument number
        inst_value = record.get("instrument_number")
        inst_family = self.classify_instrument(inst_value)
        county_data["instrument"]["families"][inst_family] += 1
        
        # Store first example for each family
        if inst_family not in county_data["instrument"]["examples"]:
            county_data["instrument"]["examples"][inst_family] = str(inst_value) if inst_value is not None else None
            county_data["instrument"]["values"][inst_family] = []
        
        # Collect examples for regex generation (capped at MAX_EXAMPLES_PER_FAMILY)
        if len(county_data["instrument"]["values"][inst_family]) < self.MAX_EXAMPLES_PER_FAMILY:
            if inst_value is not None:
                county_data["instrument"]["values"][inst_family].append(str(inst_value))
        
        # Process book and page numbers (using helper method to avoid duplication)
        self._process_book_page_field(county_data, "book", record.get("book"))
        self._process_book_page_field(county_data, "page", record.get("page"))
        
        # Process dates
        self.track_date(county, record.get("date"), str(inst_value))
        
        # Process doc_type and doc_category
        doc_type = record.get("doc_type")
        doc_category = record.get("doc_category")
        
        if doc_type:
            county_data["doc_types"][doc_type] += 1
            if doc_category:
                county_data["type_to_category"][doc_type][doc_category] += 1

    def generate_regex(self, family: str, examples: List[str]) -> Tuple[str, str]:
        """
        Generate regex pattern from family examples.
        
        Rules:
        - Detect lengths of digit/letter runs
        - If consistent (all same or tight range), use \\d{N} or \\d{min,max}
        - If variable, use \\d+ (document why in code comment)
        
        Returns (pattern_description, regex)
        """
        if not examples:
            return (family, None)
        
        # Analyze examples
        if family == "bp_prefixed":
            # Check digit lengths after "bp"
            digit_lengths = [len(ex[2:]) for ex in examples if len(ex) > 2]
            if digit_lengths:
                min_len = min(digit_lengths)
                max_len = max(digit_lengths)
                if min_len == max_len:
                    return (f"bp prefix + {min_len} digits", f"^bp\\d{{{min_len}}}$")
                elif max_len - min_len <= 2:
                    return (f"bp prefix + {min_len}-{max_len} digits", f"^bp\\d{{{min_len},{max_len}}}$")
            # Variable length
            return ("bp prefix + variable digits", "^bp\\d+$")
        
        elif family == "year_hyphen":
            # Pattern: YYYY-NNNN...
            # Extract digit parts after hyphen
            parts = [ex.split("-") for ex in examples if "-" in ex]
            if parts and all(len(p) == 2 for p in parts):
                second_lengths = [len(p[1]) for p in parts if p[1].isdigit()]
                if second_lengths:
                    min_len = min(second_lengths)
                    max_len = max(second_lengths)
                    if min_len == max_len:
                        return (f"year-{min_len}digit", f"^(19|20)\\d{{2}}-\\d{{{min_len}}}$")
                    elif max_len - min_len <= 2:
                        return (f"year-{min_len}-{max_len}digit", f"^(19|20)\\d{{2}}-\\d{{{min_len},{max_len}}}$")
            return ("year-hyphen-variable", "^(19|20)\\d{2}-\\d+$")
        
        elif family == "hyphenated":
            # Analyze hyphen positions and digit lengths
            parts = [ex.split("-") for ex in examples if "-" in ex]
            if parts and len(parts) > 5:
                # Check if consistent structure
                num_parts = [len(p) for p in parts]
                if len(set(num_parts)) == 1 and num_parts[0] == 2:
                    # Two-part hyphenated
                    first_lengths = [len(p[0]) for p in parts if p[0].isdigit()]
                    second_lengths = [len(p[1]) for p in parts if len(p) > 1 and p[1].isdigit()]
                    
                    if first_lengths and second_lengths:
                        min_first = min(first_lengths)
                        max_first = max(first_lengths)
                        min_second = min(second_lengths)
                        max_second = max(second_lengths)
                        
                        if min_first == max_first and min_second == max_second:
                            return (f"{min_first}digit-{min_second}digit", f"^\\d{{{min_first}}}-\\d{{{min_second}}}$")
                        elif max_first - min_first <= 1 and max_second - min_second <= 1:
                            return (f"{min_first}-{max_first}digit hyphen {min_second}-{max_second}digit",
                                   f"^\\d{{{min_first},{max_first}}}-\\d{{{min_second},{max_second}}}$")
            return ("hyphenated (variable)", "^\\d+-\\d+$")
        
        elif family == "year_prefixed":
            # YYYYNNNN...
            lengths = [len(ex) for ex in examples if ex.isdigit() and len(ex) > 4]
            if lengths:
                min_len = min(lengths)
                max_len = max(lengths)
                if min_len == max_len:
                    return (f"{min_len}digit year-prefixed", f"^(19|20)\\d{{{min_len-2}}}$")
                elif max_len - min_len <= 2:
                    return (f"{min_len}-{max_len}digit year-prefixed", f"^(19|20)\\d{{{min_len-2},{max_len-2}}}$")
            return ("year-prefixed (variable)", "^(19|20)\\d+$")
        
        elif family == "pure_numeric":
            lengths = [len(ex) for ex in examples if ex.isdigit()]
            if lengths:
                min_len = min(lengths)
                max_len = max(lengths)
                if min_len == max_len:
                    return (f"{min_len}digit numeric", f"^\\d{{{min_len}}}$")
                elif max_len - min_len <= 3:
                    return (f"{min_len}-{max_len}digit numeric", f"^\\d{{{min_len},{max_len}}}$")
            # Variable length - use \\d+ when variability is truly present
            return ("numeric (variable length)", "^\\d+$")
        
        elif family == "numeric":
            # For book/page
            lengths = [len(ex) for ex in examples if ex.isdigit()]
            if lengths:
                min_len = min(lengths)
                max_len = max(lengths)
                if min_len == max_len:
                    return (f"{min_len}digit numeric", f"^\\d{{{min_len}}}$")
                elif max_len - min_len <= 3:
                    return (f"{min_len}-{max_len}digit numeric", f"^\\d{{{min_len},{max_len}}}$")
            return ("numeric (variable)", "^\\d+$")
        
        elif family == "zero_padded_numeric":
            lengths = [len(ex) for ex in examples if ex.isdigit()]
            if lengths:
                min_len = min(lengths)
                max_len = max(lengths)
                if min_len == max_len:
                    return (f"{min_len}digit zero-padded", f"^0\\d{{{min_len-1}}}$")
                elif max_len - min_len <= 2:
                    return (f"{min_len}-{max_len}digit zero-padded", f"^0\\d{{{min_len-1},{max_len-1}}}$")
            return ("zero-padded numeric", "^0\\d+$")
        
        elif family == "alphanumeric":
            return ("alphanumeric", "^[a-zA-Z0-9]+$")
        
        return (family, None)

    def generate_instrument_patterns(self, county: str) -> List[Dict[str, Any]]:
        """
        Generate instrument_patterns list for county.
        
        Strategy:
        - Always include top 3-5 families (even if small)
        - Optionally add families > threshold (2% or 100 records)
        - Group remaining into "other/anomalies" bucket
        """
        county_data = self.data[county]
        families = county_data["instrument"]["families"]
        total = county_data["record_count"]
        
        if total == 0:
            return []
        
        # Sort by count descending, exclude null_value from main patterns
        sorted_families = sorted(
            [(fam, count) for fam, count in families.items() if fam != "null_value"],
            key=lambda x: x[1],
            reverse=True
        )
        
        patterns = []
        included_count = 0
        included_families = set()
        threshold = max(total * self.OTHER_BUCKET_THRESHOLD_PCT, 
                       self.OTHER_BUCKET_THRESHOLD_MIN)
        
        # Always include top N patterns
        top_n = min(self.TOP_N_PATTERNS, len(sorted_families))
        for i, (family, count) in enumerate(sorted_families):
            if i < top_n or count >= threshold:
                example_values = county_data["instrument"]["values"].get(family, [])
                pattern_desc, regex = self.generate_regex(family, example_values)
                example = county_data["instrument"]["examples"].get(family)
                
                patterns.append({
                    "pattern": pattern_desc,
                    "regex": regex,
                    "example": example,
                    "count": count,
                    "percentage": round(count / total * 100, 1)
                })
                included_count += count
                included_families.add(family)
            else:
                break
        
        # Group remaining into "other/anomalies"
        other_count = total - included_count - families.get("null_value", 0)
        if other_count > 0:
            # Find an example from remaining families (not in included_families set)
            other_example = None
            for family, count in sorted_families:
                if family not in included_families:
                    other_example = county_data["instrument"]["examples"].get(family)
                    break
            
            patterns.append({
                "pattern": "other/anomalies",
                "regex": None,
                "example": other_example,
                "count": other_count,
                "percentage": round(other_count / total * 100, 1)
            })
        
        return patterns

    def generate_book_page_patterns(self, county: str, field: str) -> Tuple[List[Dict[str, Any]], int]:
        """
        Generate book_patterns or page_patterns list for county.
        
        Returns (patterns_list, null_count)
        """
        county_data = self.data[county]
        field_data = county_data[field]
        families = field_data["families"]
        total = county_data["record_count"]
        
        null_count = families.get("null_value", 0)
        non_null_total = total - null_count
        
        if non_null_total == 0:
            return ([], null_count)
        
        # Sort by count descending, exclude null_value
        sorted_families = sorted(
            [(fam, count) for fam, count in families.items() if fam != "null_value"],
            key=lambda x: x[1],
            reverse=True
        )
        
        patterns = []
        
        # Check if zero_padded should be merged with numeric
        zero_padded_count = families.get("zero_padded_numeric", 0)
        numeric_count = families.get("numeric", 0)
        
        merge_zero_padded = False
        if zero_padded_count > 0 and non_null_total > 0:
            if zero_padded_count / non_null_total < self.ZERO_PADDED_MERGE_THRESHOLD:
                merge_zero_padded = True
        
        for family, count in sorted_families:
            # Skip zero_padded if merging
            if merge_zero_padded and family == "zero_padded_numeric":
                continue
            
            example_values = field_data["values"].get(family, [])
            
            # Adjust count if merging
            actual_count = count
            if merge_zero_padded and family == "numeric":
                actual_count = numeric_count + zero_padded_count
            
            pattern_desc, regex = self.generate_regex(family, example_values)
            example = field_data["examples"].get(family)
            
            pattern_obj = {
                "pattern": pattern_desc,
                "regex": regex,
                "example": example,
                "count": actual_count,
                "percentage": round(actual_count / non_null_total * 100, 1),
                "null_count": 0
            }
            
            # Add range for numeric families (family-specific)
            if family in ["numeric", "zero_padded_numeric"]:
                # If merging zero_padded into numeric, combine their ranges
                if merge_zero_padded and family == "numeric":
                    numeric_vals = county_data[field]["numeric_values_by_family"]["numeric"]
                    zero_padded_vals = county_data[field]["numeric_values_by_family"]["zero_padded_numeric"]
                    combined_vals = numeric_vals + zero_padded_vals
                    if combined_vals:
                        pattern_obj["range"] = {
                            "min": min(combined_vals),
                            "max": max(combined_vals)
                        }
                    else:
                        pattern_obj["range"] = None
                else:
                    # Normal case: use only this family's values
                    family_numeric_vals = county_data[field]["numeric_values_by_family"][family]
                    if family_numeric_vals:
                        pattern_obj["range"] = {
                            "min": min(family_numeric_vals),
                            "max": max(family_numeric_vals)
                        }
                    else:
                        pattern_obj["range"] = None
            else:
                pattern_obj["range"] = None
            
            patterns.append(pattern_obj)
        
        return (patterns, null_count)

    def generate_output(self) -> Dict[str, Any]:
        """Format results per county according to strict schema."""
        output = {}
        
        for county in sorted(self.data.keys()):
            county_data = self.data[county]
            
            # Instrument patterns
            instrument_patterns = self.generate_instrument_patterns(county)
            
            # Book patterns
            book_patterns, book_null_count = self.generate_book_page_patterns(county, "book")
            
            # Page patterns
            page_patterns, page_null_count = self.generate_book_page_patterns(county, "page")
            
            # Date range and anomalies
            date_range = {
                "earliest": county_data["dates"]["min"].isoformat() if county_data["dates"]["min"] else None,
                "latest": county_data["dates"]["max"].isoformat() if county_data["dates"]["max"] else None,
                "anomalies": []
            }
            
            # Format anomalies (all 4 types, even if empty)
            # count = total occurrences, examples = capped sample
            for anomaly_type in ["future_date", "very_old_date", "null_date", "unparseable_date"]:
                examples = county_data["anomalies"][anomaly_type]
                total_count = county_data["anomaly_counts"][anomaly_type]
                date_range["anomalies"].append({
                    "type": anomaly_type,
                    "count": total_count,
                    "examples": examples
                })
            
            # Doc type distribution (top 10 only)
            doc_types = county_data["doc_types"]
            top_10_doc_types = dict(doc_types.most_common(10))
            
            # Doc type to category mapping
            type_to_cat = county_data["type_to_category"]
            ambiguous_examples = []
            max_categories = 0
            
            for doc_type, categories in type_to_cat.items():
                num_categories = len(categories)
                if num_categories > max_categories:
                    max_categories = num_categories
                
                if num_categories > 1 and len(ambiguous_examples) < 10:
                    ambiguous_examples.append({
                        "doc_type": doc_type,
                        "categories": dict(categories)
                    })
            
            doc_type_mapping = {
                "ambiguous_count": len([dt for dt, cats in type_to_cat.items() if len(cats) > 1]),
                "max_categories_per_doc_type": max_categories,
                "examples": ambiguous_examples
            }
            
            # Build county output
            output[county] = {
                "record_count": county_data["record_count"],
                "instrument_patterns": instrument_patterns,
                "book_patterns": book_patterns,
                "book_null_count": book_null_count,
                "page_patterns": page_patterns,
                "page_null_count": page_null_count,
                "date_range": date_range,
                "doc_type_distribution": top_10_doc_types,
                "unique_doc_types": len(doc_types),
                "doc_type_to_category_mapping": doc_type_mapping
            }
        
        return output


def main():
    """Entry point for pattern analyzer."""
    # Define paths
    base_dir = Path(__file__).parent.parent.parent
    input_file = base_dir / "nc_records_assessment.jsonl"
    output_file = Path(__file__).parent.parent / "outputs" / "county_patterns.json"
    
    # Ensure output directory exists
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Initialize analyzer
    analyzer = PatternAnalyzer()
    
    print(f"Reading records from: {input_file}")
    print("Processing records (streaming mode)...")
    
    # Stream JSONL line-by-line
    line_count = 0
    error_count = 0
    failed_lines = []  # Track first 10 failed line numbers for debugging
    
    try:
        with open(input_file, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, start=1):
                line_count += 1
                
                # Progress indicator
                if line_count % 1000 == 0:
                    print(f"  Processed {line_count} records...", end="\r")
                
                if not line.strip():
                    continue
                
                try:
                    record = json.loads(line)
                    analyzer.process_record(record)
                except json.JSONDecodeError as e:
                    error_count += 1
                    if len(failed_lines) < 10:
                        failed_lines.append(line_num)
                    print(f"\nError parsing line {line_num}: {e}", file=sys.stderr)
                    print(f"  Content preview: {line[:100]}...", file=sys.stderr)
                    continue
                except Exception as e:
                    error_count += 1
                    if len(failed_lines) < 10:
                        failed_lines.append(line_num)
                    print(f"\nError processing line {line_num}: {e}", file=sys.stderr)
                    continue
        
        # Clear progress indicator and print final summary
        print(" " * 60, end="\r")
        print(f"Processed {line_count} records ({error_count} errors)")
        
        if failed_lines:
            print(f"Failed line numbers (first 10): {failed_lines}", file=sys.stderr)
        
        # Generate output
        print("Generating pattern analysis...")
        output = analyzer.generate_output()
        
        # Write output
        print(f"Writing results to: {output_file}")
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        
        # Summary
        print("\n" + "="*60)
        print("PATTERN ANALYSIS COMPLETE")
        print("="*60)
        print(f"Counties analyzed: {len(output)}")
        print(f"Total records: {sum(data['record_count'] for data in output.values())}")
        print(f"Output file: {output_file}")
        print("="*60)
        
    except FileNotFoundError:
        print(f"Error: Input file not found: {input_file}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

