"""
Test runner for Seminole County scraper with all test cases.

Runs 3 test cases:
1. SMITH JOHN - Large result set (2000+ expected)
2. JONES, WILLIAM S - Moderate result set (~55 expected)
3. ZZZTEST, NORESULT - Zero results expected
"""

import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Any, Tuple

from seminole_scraper import SeminoleScraper


def run_test_case(scraper: SeminoleScraper, name: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Run a single test case and collect metrics and records.
    
    Args:
        scraper: SeminoleScraper instance
        name: Name to search
        
    Returns:
        Tuple of (metrics_dict, records_list)
    """
    print(f"\n{'='*60}")
    print(f"TEST CASE: {name}")
    print(f"{'='*60}")
    
    start_time = time.time()
    
    try:
        records = scraper.search_by_name(name)
        duration = time.time() - start_time
        
        print(f"✅ Success: {len(records)} records in {duration:.1f}s")
        
        metrics = {
            "search_name": name,
            "record_count": len(records),
            "duration_seconds": round(duration, 1),
            "errors": 0,
            "status": "success"
        }
        return metrics, records
        
    except Exception as e:
        duration = time.time() - start_time
        error = str(e)
        
        print(f"❌ Failed: {error}")
        
        metrics = {
            "search_name": name,
            "record_count": 0,
            "duration_seconds": round(duration, 1),
            "errors": 1,
            "error_message": error,
            "status": "failed"
        }
        return metrics, []


def main():
    """Run all test cases and generate consolidated output."""
    
    # Test names as specified in requirements
    test_names = [
        "SMITH JOHN",
        "JONES, WILLIAM S",
        "ZZZTEST, NORESULT"
    ]
    
    output_path = Path("outputs/seminole_test_results.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Initialize scraper (headless mode for automated testing)
    print("Initializing Seminole County scraper...")
    scraper = SeminoleScraper(headless=True)
    
    test_results = []
    all_records = []
    
    try:
        # Run each test case (single scrape per name - no duplicates)
        for name in test_names:
            metrics, records = run_test_case(scraper, name)
            test_results.append(metrics)
            all_records.extend(records)
        
        # Calculate aggregate performance metrics
        total_records = sum(r["record_count"] for r in test_results)
        total_duration = sum(r["duration_seconds"] for r in test_results)
        records_per_minute = (total_records / total_duration * 60) if total_duration > 0 else 0
        
        print(f"\n{'='*60}")
        print("TEST SUMMARY")
        print(f"{'='*60}")
        print(f"Total tests: {len(test_results)}")
        print(f"Successful: {sum(1 for r in test_results if r['status'] == 'success')}")
        print(f"Failed: {sum(1 for r in test_results if r['status'] == 'failed')}")
        print(f"Total records: {total_records}")
        print(f"Total duration: {total_duration:.1f}s")
        print(f"Performance: {records_per_minute:.1f} records/minute")
        print(f"{'='*60}\n")
        
        # Write output as plain JSON array (NO metadata wrapper)
        # CRITICAL: Assignment requires same format as NC dataset
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(all_records, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Output saved to: {output_path}")
        print(f"   {len(all_records)} NC-schema records (plain JSON array)")
        
        # Also save test summary to a separate file for documentation
        summary_path = output_path.parent / "test_summary.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            summary = {
                "test_date": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "test_cases": test_results,
                "performance": {
                    "total_records": total_records,
                    "total_duration_seconds": total_duration,
                    "records_per_minute": round(records_per_minute, 1)
                }
            }
            json.dump(summary, f, indent=2)
        
        print(f"📊 Test summary saved to: {summary_path}")
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        sys.exit(1)
    
    except Exception as e:
        print(f"\n\n❌ Fatal error: {e}", file=sys.stderr)
        sys.exit(1)
    
    finally:
        scraper.close()


if __name__ == "__main__":
    main()

