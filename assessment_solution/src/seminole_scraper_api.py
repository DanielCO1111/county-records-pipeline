"""
Seminole County FL Official Records Scraper — Hybrid API Implementation

Architecture:
  - Selenium  → used ONLY once at startup to load the page, accept the
                disclaimer, and extract the ASP.NET_SessionId cookie and
                X-Api-Token by intercepting the first real API call.
  - requests  → used for ALL actual data fetching via the internal JSON API.

Website: https://recording.seminoleclerk.org/DuProcessWebInquiry/index.html
"""

import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytz
import requests
from dateutil import parser as date_parser
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager

# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────

BASE_URL = "https://recording.seminoleclerk.org/DuProcessWebInquiry"
SEARCH_ENDPOINT = f"{BASE_URL}/Home/CriteriaSearch"
OUTPUT_PATH = Path("outputs") / "seminole_test_results.json"
DATE_START_DEFAULT = "1/1/1913"
REQUEST_DELAY = 1.5
MAX_RETRIES = 3
RETRY_BACKOFF = 2

NC_SCHEMA_KEYS = {
    "instrument_number", "parcel_number", "county", "state", "book", "page",
    "doc_type", "doc_category", "original_doc_type", "book_type",
    "grantors", "grantees", "date", "consideration"
}
MUST_BE_NULL_FIELDS = {"parcel_number", "doc_category", "book_type", "consideration"}
ET_TIMEZONE = pytz.timezone("America/New_York")

TEST_CASES = [
    {"name": "Smith john jr", "expected_count": 16},
    {"name": "Smith john C",  "expected_count": 81},
    {"name": "XYZ ABC",       "expected_count": 0},
]

HEADERS = {
    "Accept":          "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control":   "no-cache",
    "Pragma":          "no-cache",
    "Referer":         f"{BASE_URL}/index.html",
    "Sec-Fetch-Dest":  "empty",
    "Sec-Fetch-Mode":  "cors",
    "Sec-Fetch-Site":  "same-origin",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/145.0.0.0 Safari/537.36"
    ),
}


# ─────────────────────────────────────────────
# Scraper Class
# ─────────────────────────────────────────────

class SeminoleAPIScraper:

    def __init__(self):
        self.logger = self._setup_logging()
        self.session = self._setup_session()
        self._init_session()

    def _setup_logging(self) -> logging.Logger:
        logger = logging.getLogger("SeminoleAPIScraper")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        if not logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter(
                "[%(asctime)s] [%(levelname)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            ))
            logger.addHandler(handler)
        return logger

    def _setup_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update(HEADERS)
        return session

    def _init_session(self):
        """
        Use Selenium (headless) to:
        1. Load the page and accept the disclaimer
        2. Extract ASP.NET_SessionId cookie
        3. Trigger a real API call and intercept the X-Api-Token from it

        After this method, self.session is fully authenticated and all
        subsequent calls use requests only — no browser needed.
        """
        self.logger.info("Initializing session...")

        driver = None
        try:
            options = webdriver.ChromeOptions()
            options.add_argument("--headless")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option("useAutomationExtension", False)

            # Enable performance logging to capture network requests
            options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

            service = ChromeService(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
            driver.set_page_load_timeout(30)

            # Step 1: Load main page
            self.logger.info("Loading main page...")
            driver.get(f"{BASE_URL}/index.html")

            # Step 2: Accept disclaimer
            try:
                disclaimer = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "a.btn.btn-success"))
                )
                driver.execute_script("arguments[0].click();", disclaimer)
                self.logger.info("Disclaimer accepted")
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.ID, "criteria_full_name"))
                )
            except TimeoutException:
                self.logger.info("No disclaimer found — proceeding")

            # Step 3: Extract cookies
            for cookie in driver.get_cookies():
                self.session.cookies.set(
                    cookie["name"],
                    cookie["value"],
                    domain=cookie.get("domain", "").lstrip(".")
                )
            session_id = self.session.cookies.get("ASP.NET_SessionId", "NOT FOUND")
            self.logger.info(f"Session cookie ready: {session_id[:8]}...")

            # Step 4: Trigger a real API call by performing a search in the browser
            # Then intercept the X-Api-Token from the performance logs
            self.logger.info("Triggering API call to capture X-Api-Token...")

            name_input = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.ID, "criteria_full_name"))
            )
            driver.execute_script("arguments[0].scrollIntoView(true);", name_input)
            time.sleep(0.5)
            driver.execute_script("arguments[0].value = 'Smith';", name_input)

            # Click search button
            try:
                search_btn = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH,
                        "//*[(self::a or self::button) and contains("
                        "translate(normalize-space(.), "
                        "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'search')]"
                    ))
                )
                driver.execute_script("arguments[0].click();", search_btn)
            except Exception as e:
                self.logger.warning(f"Could not click search: {e}")

            # Wait a moment for the API call to fire
            time.sleep(3)

            # Parse performance logs to find X-Api-Token
            api_token = None
            try:
                logs = driver.get_log("performance")
                for entry in logs:
                    message = json.loads(entry["message"])["message"]
                    if message.get("method") == "Network.requestWillBeSent":
                        req = message.get("params", {}).get("request", {})
                        url = req.get("url", "")
                        if "CriteriaSearch" in url:
                            headers = req.get("headers", {})
                            # Try different capitalizations
                            for key in headers:
                                if key.lower() == "x-api-token":
                                    api_token = headers[key]
                                    break
                        if api_token:
                            break
            except Exception as e:
                self.logger.warning(f"Performance log parsing failed: {e}")

            if api_token:
                self.session.headers.update({"X-Api-Token": api_token})
                self.logger.info(f"X-Api-Token captured: {api_token[:8]}...")
            else:
                self.logger.warning("X-Api-Token not captured — will try without it")

            self.logger.info("Session ready. Switching to requests for all API calls.")

        except Exception as e:
            self.logger.error(f"Session init failed: {e}")
            raise
        finally:
            if driver:
                driver.quit()
                self.logger.info("Browser closed")

    def _build_criteria(self, name: str) -> str:
        today = datetime.now().strftime("%m/%d/%Y").lstrip("0").replace("/0", "/")
        criteria = [{
            "direction": "",
            "name_direction": True,
            "full_name": name,
            "file_date_start": DATE_START_DEFAULT,
            "file_date_end": today,
            "inst_type": "",
            "inst_book_type_id": "",
            "location_id": "",
            "book_reel": "",
            "page_image": "",
            "greater_than_page": False,
            "inst_num": "",
            "description": "",
            "consideration_value_min": "",
            "consideration_value_max": "",
            "parcel_id": "",
            "legal_section": "",
            "legal_township": "",
            "legal_range": "",
            "legal_square": "",
            "subdivision_code": "",
            "block": "",
            "lot_from": "",
            "q_NWNW": False, "q_NWNE": False, "q_NWSE": False, "q_NWSW": False,
            "q_NENW": False, "q_NENE": False, "q_NESE": False, "q_NESW": False,
            "q_SWNW": False, "q_SWNE": False, "q_SWSE": False, "q_SWSW": False,
            "q_SENW": False, "q_SENE": False, "q_SESE": False, "q_SESW": False,
            "q_q_search_type": False,
            "address_street": "",
            "address_number": "",
            "address_parcel": "",
            "address_ppin": "",
            "patent_number": "",
        }]
        return json.dumps(criteria)

    def _fetch_page(self, name: str) -> List[Dict]:
        params = {"criteria_array": self._build_criteria(name)}
        last_exc = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                self.logger.info(f"API request (attempt {attempt}/{MAX_RETRIES}): name='{name}'")
                response = self.session.get(SEARCH_ENDPOINT, params=params, timeout=60)
                self.logger.info(f"Response status: {response.status_code}")
                response.raise_for_status()

                data = response.json()
                if isinstance(data, list):
                    self.logger.info(f"API returned {len(data)} records")
                    return data
                if isinstance(data, dict):
                    for key in ("results", "data", "records", "items"):
                        if key in data and isinstance(data[key], list):
                            return data[key]
                return []

            except requests.HTTPError as e:
                last_exc = e
                self.logger.warning(f"HTTP error on attempt {attempt}: {e}")
            except (requests.ConnectionError, requests.Timeout) as e:
                last_exc = e
                self.logger.warning(f"Network error on attempt {attempt}: {e}")
            except json.JSONDecodeError as e:
                self.logger.error(f"JSON decode error: {e}")
                break

            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF * attempt
                self.logger.info(f"Retrying in {wait}s...")
                time.sleep(wait)

        self.logger.error(f"All {MAX_RETRIES} attempts failed: {last_exc}")
        return []

    def _parse_date(self, date_str: Optional[str]) -> Optional[str]:
        if not date_str:
            return None
        try:
            dt = date_parser.parse(date_str)
            if dt.tzinfo is None:
                dt = ET_TIMEZONE.localize(dt)
            else:
                dt = dt.astimezone(ET_TIMEZONE)
            return dt.isoformat()
        except Exception as e:
            self.logger.warning(f"Failed to parse date '{date_str}': {e}")
            return None

    def _to_nc_schema(self, raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        instrument_number = raw.get("inst_num") or raw.get("gin")
        if not instrument_number:
            return None

        party_name = raw.get("party_name", "").strip().upper() or None
        cross_party = raw.get("cross_party_name", "").strip().upper() or None
        direction = raw.get("direction", "").strip()

        if direction == "From":
            grantors = [party_name] if party_name else None
            grantees = [cross_party] if cross_party else None
        elif direction == "To":
            grantors = [cross_party] if cross_party else None
            grantees = [party_name] if party_name else None
        else:
            grantors = [party_name] if party_name else None
            grantees = [cross_party] if cross_party else None

        doc_type_raw = raw.get("instrument_type", "").strip()
        book = str(raw.get("book_reel", "")).strip() or None
        page = str(raw.get("page", "")).strip() or None

        return {
            "instrument_number": str(instrument_number).strip(),
            "parcel_number":     None,
            "county":            "seminole",
            "state":             "FL",
            "book":              book,
            "page":              page,
            "doc_type":          doc_type_raw.upper() if doc_type_raw else None,
            "doc_category":      None,
            "original_doc_type": doc_type_raw or None,
            "book_type":         None,
            "grantors":          grantors,
            "grantees":          grantees,
            "date":              self._parse_date(raw.get("file_date")),
            "consideration":     None,
        }

    def search_by_name(self, name: str) -> List[Dict[str, Any]]:
        self.logger.info(f"Searching for: '{name}'")
        start = time.time()

        time.sleep(REQUEST_DELAY)
        raw_records = self._fetch_page(name)

        if not raw_records:
            self.logger.info(f"No records found for '{name}'")
            return []

        nc_records = [r for r in (self._to_nc_schema(raw) for raw in raw_records) if r]

        duration = time.time() - start
        rpm = (len(nc_records) / duration * 60) if duration > 0 else 0
        self.logger.info(f"Done: {len(nc_records)} records in {duration:.1f}s ({rpm:.1f} rec/min)")
        return nc_records


# ─────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────

def validate_records(records, expected_count=None):
    errors = []
    count_match = True
    if expected_count is not None:
        count_match = len(records) == expected_count
        if not count_match:
            errors.append(f"Count mismatch: expected {expected_count}, got {len(records)}")

    schema_keys_ok = True
    for idx, record in enumerate(records):
        missing = NC_SCHEMA_KEYS - set(record.keys())
        extra = set(record.keys()) - NC_SCHEMA_KEYS
        if missing or extra:
            schema_keys_ok = False
            if missing: errors.append(f"Record {idx}: missing keys {missing}")
            if extra:   errors.append(f"Record {idx}: extra keys {extra}")

    nulls_ok = True
    for idx, record in enumerate(records):
        for field in MUST_BE_NULL_FIELDS:
            if record.get(field) is not None:
                nulls_ok = False
                errors.append(f"Record {idx}: {field} should be None")
        for party in ("grantors", "grantees"):
            val = record.get(party)
            if isinstance(val, list) and len(val) == 0:
                nulls_ok = False
                errors.append(f"Record {idx}: {party} is empty list (should be None)")

    uppercase_names_ok = True
    for idx, record in enumerate(records):
        for party in ("grantors", "grantees"):
            for i, n in enumerate(record.get(party) or []):
                if isinstance(n, str) and n != n.upper():
                    uppercase_names_ok = False
                    errors.append(f"Record {idx}: {party}[{i}] not uppercase: {n!r}")

    date_timezone_ok = True
    for idx, record in enumerate(records):
        d = record.get("date")
        if d is not None:
            has_tz = d.endswith("Z") or bool(re.search(r'[+-]\d{2}:\d{2}$', d))
            if "T" not in d or not has_tz:
                date_timezone_ok = False
                errors.append(f"Record {idx}: bad date format: {d!r}")

    no_links_ok = True
    for idx, record in enumerate(records):
        for field in ["instrument_number", "book", "page", "doc_type", "original_doc_type", "date"]:
            val = record.get(field)
            if isinstance(val, str) and ("http://" in val.lower() or "https://" in val.lower()):
                no_links_ok = False
                errors.append(f"Record {idx}: {field} contains URL")

    return {
        "count_match": count_match,
        "schema_keys_ok": schema_keys_ok,
        "nulls_ok": nulls_ok,
        "uppercase_names_ok": uppercase_names_ok,
        "date_timezone_ok": date_timezone_ok,
        "no_links_ok": no_links_ok,
        "errors": errors,
    }


def is_test_passed(v):
    return all([v["count_match"], v["schema_keys_ok"], v["nulls_ok"],
                v["uppercase_names_ok"], v["date_timezone_ok"], v["no_links_ok"],
                len(v["errors"]) == 0])


# ─────────────────────────────────────────────
# Test Suite
# ─────────────────────────────────────────────

def run_test_suite(scraper, logger):
    et_tz = pytz.timezone("America/New_York")
    generated_at = datetime.now(et_tz).isoformat()
    results, passed, failed = [], 0, 0

    for idx, tc in enumerate(TEST_CASES):
        logger.info("=" * 60)
        logger.info(f"TEST {idx+1}/{len(TEST_CASES)}: '{tc['name']}' (expected: {tc['expected_count']})")
        logger.info("=" * 60)
        try:
            records = scraper.search_by_name(tc["name"])
            v = validate_records(records, tc["expected_count"])
            ok = is_test_passed(v)
            if ok:
                passed += 1
                logger.info(f"✓ PASSED: '{tc['name']}' — {len(records)} records")
            else:
                failed += 1
                logger.warning(f"✗ FAILED: '{tc['name']}' — {len(records)} records")
                for err in v["errors"][:5]: logger.warning(f"  - {err}")
            results.append({"name": tc["name"], "expected_count": tc["expected_count"],
                            "actual_count": len(records), "validations": v, "records": records})
        except Exception as e:
            failed += 1
            logger.error(f"✗ EXCEPTION: {e}")
            results.append({"name": tc["name"], "expected_count": tc["expected_count"],
                            "actual_count": 0,
                            "validations": {"count_match": False, "schema_keys_ok": False,
                                            "nulls_ok": False, "uppercase_names_ok": False,
                                            "date_timezone_ok": False, "no_links_ok": False,
                                            "errors": [str(e)]},
                            "records": []})
        if idx < len(TEST_CASES) - 1:
            time.sleep(REQUEST_DELAY)

    logger.info(f"SUITE COMPLETE: {passed} passed, {failed} failed")
    return {"generated_at": generated_at, "county": "seminole", "state": "FL",
            "tests": results, "summary": {"passed": passed, "failed": failed}}


def run_single_search(scraper, name, logger):
    et_tz = pytz.timezone("America/New_York")
    generated_at = datetime.now(et_tz).isoformat()
    try:
        records = scraper.search_by_name(name)
        v = validate_records(records)
        passed = is_test_passed(v)
        return {"generated_at": generated_at, "county": "seminole", "state": "FL",
                "tests": [{"name": name, "expected_count": None,
                           "actual_count": len(records), "validations": v, "records": records}],
                "summary": {"passed": 1 if passed else 0, "failed": 0 if passed else 1}}
    except Exception as e:
        logger.error(f"Search failed: {e}")
        return {"generated_at": generated_at, "county": "seminole", "state": "FL",
                "tests": [{"name": name, "expected_count": None, "actual_count": 0,
                           "validations": {"count_match": True, "schema_keys_ok": False,
                                           "nulls_ok": False, "uppercase_names_ok": False,
                                           "date_timezone_ok": False, "no_links_ok": False,
                                           "errors": [str(e)]}, "records": []}],
                "summary": {"passed": 0, "failed": 1}}


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Seminole County FL scraper — Hybrid API")
    parser.add_argument("--name", help="Name to search")
    parser.add_argument("--run-tests", action="store_true", dest="run_tests")
    args = parser.parse_args()

    if not args.run_tests and not args.name:
        parser.error("Either --name or --run-tests is required")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    scraper = SeminoleAPIScraper()
    logger = scraper.logger

    try:
        if args.run_tests:
            results = run_test_suite(scraper, logger)
            s = results["summary"]
            total = sum(t["actual_count"] for t in results["tests"])
            if s["failed"] == 0:
                print(f"\n✅ TEST SUITE PASSED: {s['passed']}/3 tests, {total} total records")
            else:
                print(f"\n⚠️  {s['passed']} passed, {s['failed']} failed, {total} records")
        else:
            results = run_single_search(scraper, args.name, logger)
            t = results["tests"][0]
            if is_test_passed(t["validations"]):
                print(f"\n✅ Success: {t['actual_count']} records")
            else:
                print(f"\n⚠️  {t['actual_count']} records ({len(t['validations']['errors'])} warnings)")

        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"📁 Results saved to {OUTPUT_PATH}")

    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()