# 📊 Dono Data Engineer Assessment

> **Solution repository for the Dono Data Engineering take-home assignment**

---

## 📋 Tasks Overview

### ✅ Task 1: County Pattern Analysis (COMPLETE)
**Script:** `src/pattern_analyzer.py`  
**Output:** `outputs/county_patterns.json`  
**Objective:** Extract and document patterns in instrument numbers, book/page numbers, date ranges, and document types for each of the 13 NC counties.

### ✅ Task 2: Seminole County FL Scraper (COMPLETE)
**Script:** `src/seminole_scraper.py`  
**Output:** `outputs/seminole_test_results.json`  
**Objective:** Scrape Seminole County FL official records and convert to NC schema format for system compatibility.

---

## 📁 Project Structure

```
assessment_solution/
├── src/
│   ├── pattern_analyzer.py       # Task 1: County pattern analysis
│   └── seminole_scraper.py       # Task 2: FL county scraper (includes --run-tests)
├── outputs/
│   ├── county_patterns.json      # Task 1: Analysis results
│   └── seminole_test_results.json # Task 2: Scraped FL records (ONLY output file)
├── requirements.txt               # Python dependencies
├── pyproject.toml                # Code formatting/linting configuration
└── README.md                     # This file

../  (parent directory)
├── nc_records_assessment.jsonl  # Input: JSONL data (~14K records, ~2-3 MB)
└── records/                     # Input: PDF files by county (optional for Task 1)
    ├── alamance/
    ├── buncombe/
    ├── cabarrus/
    ├── cumberland/
    ├── davidson/
    ├── durham/
    ├── forsyth/
    ├── guilford/
    ├── johnston/
    ├── mecklenburg/
    ├── onslow/
    ├── union/
    └── wake/
```

> **Note:** Input data files are stored one directory above and are **not committed to git** due to size.

---

## 🎯 Requirements

### Python Version
- **Minimum:** Python 3.9
- **Tested on:** Python 3.13
- **Platform:** Windows/Linux/macOS (cross-platform compatible)

### Dependencies

All Python dependencies are listed in `requirements.txt`:

```txt
# Task 2 (Seminole Scraper) - REQUIRED
selenium          # Browser automation for dynamic websites
webdriver-manager # Automatic ChromeDriver management
pytz              # Timezone handling for ET/EST conversions
python-dateutil   # Date parsing

# Optional / Development only (NOT required for Tasks 1-2)
pandas            # Data manipulation (optional)
tqdm              # Progress bars (optional)
requests          # HTTP requests (dev exploration only)
beautifulsoup4    # HTML parsing (dev exploration only)
lxml              # XML processing (dev exploration only)
black             # Code formatter (dev)
ruff              # Python linter (dev)
```

**Note:** 
- Task 1 (`pattern_analyzer.py`) uses only Python standard library
- Task 2 (`seminole_scraper.py`) requires only: `selenium`, `webdriver-manager`, `pytz`, `python-dateutil`
- Other packages are optional/dev-only and not used by the submission scripts

### Data Requirements

**Input files must be located in parent directory:**
- `../nc_records_assessment.jsonl` (13,886 records, ~2-3 MB)
- `../records/` (PDF files by county - optional for pattern analysis)

**Output directory:**
- `assessment_solution/outputs/` (created automatically if missing)

---

## 🚀 Setup Instructions

### 1️⃣ Create Virtual Environment

**Windows (CMD):**
```bash
python -m venv .venv
.\.venv\Scripts\activate
```

**Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**Linux/macOS:**
```bash
python -m venv .venv
source .venv/bin/activate
```

### 2️⃣ Install Dependencies

```bash
python -m pip install -U pip
python -m pip install -r requirements.txt
```

---

## 🎨 Code Style

This project follows **PEP-8** conventions enforced by:

- **Black:** Code formatter
- **Ruff:** Fast Python linter

### Check Code Style
```bash
ruff check .
black --check .
```

### Auto-Format Code
```bash
black .
```

**Configuration:** See `pyproject.toml` for formatting rules (100 char line length, Python 3.9 target).

---

## 💻 Usage

### Task 1: County Pattern Analysis

**Objective:** Extract and document patterns in instrument numbers, book/page numbers, date ranges, and document types for each county.

**Run the script:**

```bash
cd assessment_solution
python src/pattern_analyzer.py
```

**Output:** `outputs/county_patterns.json`

**What it does:**
- Analyzes instrument number formats (regex patterns, counts, percentages)
- Identifies book/page number patterns with ranges
- Tracks date ranges and anomalies (future dates, very old dates, nulls)
- Generates document type distribution (top 10) and category mappings
- Processes 13,886 records in 5-10 seconds

---

## 📝 Task 1: Input Data Format

### `nc_records_assessment.jsonl`
- **Format:** JSONL (one JSON record per line)
- **Records:** 13,886 entries
- **Location:** Parent directory (`../nc_records_assessment.jsonl`)
- **Structure:** Each line contains a property record with fields like:
  - `instrument_number`, `parcel_number`, `county`, `state`
  - `book`, `page`, `doc_type`, `doc_category`
  - `grantors`, `grantees`, `date`, `consideration`

### `records/` Directory
- **Format:** PDF files (not used in Task 1)
- **Organization:** `county/instrument_number.pdf`
- **Counties:** 13 total (alamance, buncombe, cabarrus, cumberland, davidson, durham, forsyth, guilford, johnston, mecklenburg, onslow, union, wake)

---

## 📋 Key Assumptions & Design Decisions

> **Critical for Testers:** These assumptions were made based on requirements analysis and data inspection.

### ⚠️ Critical Assumptions

**1. Earliest Valid Transaction Year: 1900**
- The analysis operates on the assumption that the **earliest valid transaction year is 1900**
- Any dates prior to `1900-01-01` are categorized as **suspicious anomalies** and flagged in the output
- **Rationale:** Property records from before 1900 are extremely rare and likely represent data entry errors (e.g., "1490" found in dataset)
- These are tracked under the `very_old_date` anomaly type

**2. "bp" Prefix Case-Sensitivity (Lowercase Required)**
- The analysis **strictly requires the "bp" prefix to be lowercase** for synthetic ID pattern identification
- Instrument numbers like `bp8324`, `bp01916501155` are recognized as synthetic IDs
- Uppercase `BP` or mixed-case variants (e.g., `Bp`, `BP`) will **NOT** be classified as `bp_prefixed`
- Such values will fall into `alphanumeric` or `other` categories based on remaining classification rules
- **Rationale:** Adheres to provided instructions and maintains strict pattern matching consistency

**3. Null Values Treated as Data Quality Anomalies**
- All **null values in critical fields** (instrument_number, book, page, date) are treated as **data anomalies**, not standard missing records
- These are explicitly tracked and reported to ensure data completeness issues are flagged during assessment
- Null counts are reported separately for each field type (e.g., `book_null_count`, `page_null_count`)
- Date nulls are additionally tracked under the `null_date` anomaly type with example records
- **Rationale:** Ensures data quality issues are visible and quantifiable in the analysis output

---

### 1. Pattern Classification Strategy

**Deterministic Precedence (No Overlaps):**

Instrument numbers are classified using strict precedence order:
1. `null_value` - Missing/empty values
2. `bp_prefixed` - Synthetic IDs (e.g., `bp8324`, `bp01916501155`)
3. `year_hyphen` - Format `YYYY-<digits>` where **digits only** after hyphen (e.g., `2023-0012345`)
4. `hyphenated` - Contains hyphen but not year-prefix (e.g., `010905-02162`)
5. `year_prefixed` - Format `YYYY<digits>` where **entire value is digits** (e.g., `2025010010`)
6. `pure_numeric` - Only digits (e.g., `12796`)
7. `alphanumeric` - Contains letters/mixed chars (e.g., `20240091879C`)
8. `other` - Edge cases

**Why Strict Format Interpretation:**
- Values like `20240091879C` (year + digits + letter) are classified as `alphanumeric`, **NOT** `year_prefixed`
- This ensures regex patterns accurately represent the actual format structure
- Helps identify data quality issues (mixed formats that may indicate errors)

### 2. Pattern Selection & Grouping

**Top-N Strategy:**
- Always includes **top 5 patterns** per county (even if small)
- Optionally includes patterns > 2% of records OR > 100 records
- Remaining patterns grouped into "other/anomalies" bucket
- **Rationale:** Captures meaningful formats while avoiding long tail of rare variations

**Merge Threshold for Zero-Padded:**
- Zero-padded numbers merged into numeric if < 5% of records
- When merged: counts combined, ranges combined, separate pattern entry removed
- **Rationale:** Avoids cluttering output with insignificant formatting variations

### 3. Date Handling

**Anomaly Types (4 categories):**
1. `future_date` - Date > today (runtime check, dynamic)
2. `very_old_date` - Date < 1900-01-01 (heuristic, catches likely errors like "1490")
3. `null_date` - Missing date value
4. `unparseable_date` - Date present but ISO format parse fails

**Parsing Strategy (Strict ISO):**
- Uses `datetime.fromisoformat()` (strict parsing)
- **Does NOT use** `dateutil.parser` (too permissive)
- Non-ISO dates → flagged as `unparseable_date` (data quality signal)
- **Rationale:** Strict parsing makes data quality issues visible

**Anomaly Reporting:**
- `count` = **total occurrences** (accurate frequency tracking)
- `examples` = capped at 5 samples (memory efficiency)
- Includes `instrument_number` for traceability

### 4. Range Computation

**Family-Specific Ranges:**
- Book/page ranges computed **per pattern family**, not field-wide
- Example: "4-digit numeric" and "5-digit zero-padded" have different ranges
- **Rationale:** Provides accurate bounds for each specific format
- When merging: ranges combined from both families

### 5. Regex Generation Rules

**Smart Length Detection:**
- Consistent lengths → `\d{5}` or `\d{4,5}`
- Variable lengths → `\d+` (documents why in pattern description)
- **Example:** `(19|20)\d{8}` for 10-digit year-prefixed (2 + 8 = 10)

**Pattern Descriptions:**
- Complex patterns → human-readable (e.g., "bp prefix + 12 digits")
- Simple patterns → type name (e.g., "alphanumeric")
- **Rationale:** Descriptive where helpful, concise where obvious

### 6. Configuration Constants

**All thresholds are configurable** (see `PatternAnalyzer` class):
- `ZERO_PADDED_MERGE_THRESHOLD = 0.05` (5%)
- `OTHER_BUCKET_THRESHOLD_PCT = 0.02` (2%)
- `OTHER_BUCKET_THRESHOLD_MIN = 100` (records)
- `MAX_EXAMPLES_PER_FAMILY = 20` (for regex generation)
- `MAX_ANOMALY_EXAMPLES = 5` (stored per type)
- `TOP_N_PATTERNS = 5` (always included)

### 7. Performance & Memory

**Streaming Architecture:**
- Processes records **line-by-line** (never loads entire file into memory)
- Memory usage: ~100 MB for 13,886 records
- Suitable for datasets up to millions of records
- **Trade-off:** Cannot do multi-pass analysis, but guarantees constant memory

**Error Handling:**
- Continues processing on individual record errors
- Logs first 10 failed line numbers with content preview
- **Rationale:** Robust handling of messy real-world data

---

## 🚀 Quick Start

```bash
# 1. Setup (one-time)
cd assessment_solution
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # Windows PowerShell
# OR
source .venv/bin/activate             # Linux/macOS

python -m pip install -U pip
python -m pip install -r requirements.txt

# 2. Run Task 1 - Pattern Analyzer
python src/pattern_analyzer.py
# Output: outputs/county_patterns.json

# 3. Run Task 2 - Seminole Scraper (single search)
python src/seminole_scraper.py --name "SMITH JOHN"
# Output: outputs/seminole_test_results.json

# 4. Run Task 2 - Full test suite (3 predefined test cases)
python src/seminole_scraper.py --run-tests
# Output: outputs/seminole_test_results.json (contains all 3 tests + validations)
```

**Expected:** 
- Task 1: Processes 13,886 records in 5-10 seconds
- Task 2: Test suite completes in ~2-3 minutes (97 total records across 3 tests)

---

## 🌐 Task 2: Seminole County FL Scraper

### Overview

Task 2 implements a production-grade web scraper for Seminole County, Florida official records that:
- Searches records by person/entity name
- Handles pagination across large result sets (2000+ records, 60+ pages)
- Converts FL data to NC schema format for system compatibility
- Follows a **conservative, schema-first approach** to ensure data fidelity

**Website:** https://recording.seminoleclerk.org/DuProcessWebInquiry/index.html

### How It Works

#### 1. Architecture

The scraper uses **Selenium WebDriver** with Chrome to interact with the dynamic DuProcess WebInquiry system:

```
User Input (Name or --run-tests) 
    ↓
Accept Disclaimer ("AGREED & ENTER")
    ↓
Fill Search Form → Click Search
    ↓
Wait for Grid (Grid-First Strategy)
    ↓
Extract Page Results
    ↓
Pagination Loop → Next Page
    ↓
Transform to NC Schema
    ↓
Run Validations
    ↓
Output JSON (outputs/seminole_test_results.json)
```

#### 2. Key Implementation Details

**Disclaimer Handling:**
- The site requires clicking "AGREED & ENTER" before accessing search
- Implementation: `_accept_disclaimer_if_present()` - idempotent, robust XPath locator

**Grid-First Wait Strategy:**
- **Primary:** Wait for grid rows to be present/populated (actual success condition)
- **Secondary:** Check for spinner disappearance (best-effort, non-blocking)
- **Rationale:** Grid presence is more reliable than spinner absence

**Pagination Handling:**
- Detects "Pg X of Y" footer text to track progress
- Client-side pagination: No network requests between pages
- Wait condition: First row's Instrument # changes (custom EC)
- Safety: Per-page timeout (60s) and total runtime limit (1 hour)
- **No artificial page caps** - scrapes all pages site indicates

**Party Assignment (Non-Semantic):**
- Grid provides "Searched Name" and "Cross Party Name" columns
- Grid does NOT explicitly label grantor vs grantee roles
- **Implementation:** Deterministic positional mapping
  - `grantors`: [Searched Name] if present, else `null`
  - `grantees`: [Cross Party Name] if present, else `null`
- ⚠️ **Important:** This is column-based assignment, NOT legal/semantic role inference

### Schema Mapping & Assumptions

#### Conservative Design Principles

This scraper follows a **schema-first, conservative approach**:

✅ **Populate:** Only fields explicitly provided by the Seminole grid  
❌ **Don't guess:** No inference, no text mining, no assumptions  
✅ **Use null:** When field unavailable (following assignment requirement)

#### Field Mapping Table

| NC Schema Field | Seminole Grid Source | Notes |
|----------------|---------------------|-------|
| `instrument_number` | "Instrument #" column | Direct mapping |
| `parcel_number` | ❌ Not available | Always `null` |
| `county` | Hardcoded | Always `"seminole"` |
| `state` | Hardcoded | Always `"FL"` |
| `book` | "Book" column | Direct mapping or `null` |
| `page` | "Page" column | Direct mapping or `null` |
| `doc_type` | "Type" column | Minimal normalization (`.upper().strip()`) |
| `doc_category` | ❌ Not available | Always `null` |
| `original_doc_type` | "Type" column | Preserved exactly as shown |
| `book_type` | ❌ Not available | Always `null` |
| `grantors` | "Searched Name" column | List if present, `null` if missing (NOT `[]`) |
| `grantees` | "Cross Party Name" column | List if present, `null` if missing (NOT `[]`) |
| `date` | "Filed" column | Parsed to ISO 8601 with ET timezone |
| `consideration` | ❌ Not available | Always `null` |

#### Critical Assumptions

**1. doc_category: Always null**
- **Assumption:** The results grid does not include a `doc_category` column
- **Rationale:** Inferring categories from "Type" string would be subjective and potentially incorrect
- **Alternative:** If site exposed explicit category data, we would map it directly

**2. book_type: Always null**
- **Assumption:** The results grid does not include a `book_type` column
- **Rationale:** We don't guess "OR" (Official Records) even if book numbers are numeric
- **Alternative:** If Book column contained prefixes (e.g., "OR 1234"), we would extract them

**3. consideration: Always null**
- **Assumption:** No explicit "Consideration" or "Amount" column in results grid
- **Rationale:** Parsing unstructured Description text for dollar amounts is brittle and violates "use null for unavailable fields" rule
- **Alternative:** If grid had explicit consideration column, we would use it

**4. Party Roles (grantors/grantees): Column-Based, Not Legal**
- **Assumption:** "Searched Name" → grantors, "Cross Party Name" → grantees
- **Rationale:** Site doesn't label legal roles; we use deterministic positional mapping
- **⚠️ Warning:** This is NOT semantic/legal role determination
- **Alternative:** If grid had explicit "Grantor" / "Grantee" columns, we would use them

**5. Empty vs null for Lists**
- **Critical:** When party name is missing, we use `null` (not `[]`)
- **Rationale:** Assignment explicitly states "use null for fields not available"
- **Example:** `"grantors": null` when Searched Name is empty

**6. Timezone Handling**
- **Assumption:** "Filed" dates are in Eastern Time (America/New_York)
- **Implementation:** Apply ET timezone with correct DST offset (-04:00 or -05:00)
- **Alternative:** If site provided explicit timezone info, we would use it

### Challenges Encountered

#### 1. Client-Side Pagination Without Network Requests

**Challenge:** Clicking "Next" doesn't trigger XHR requests; page changes are instantaneous  
**Solution:** Custom wait condition that detects when first row's Instrument # changes  
**Impact:** Reliable page transition detection without depending on network activity

#### 2. Disclaimer Gate

**Challenge:** Site requires clicking "AGREED & ENTER" before accessing search  
**Solution:** `_accept_disclaimer_if_present()` - idempotent with robust XPath locator  
**Impact:** Handles both disclaimer-present and disclaimer-absent flows gracefully

#### 3. Dynamic Grid Rendering

**Challenge:** DuProcess grid uses dynamic rendering with potential loading overlays  
**Solution:** Grid-first wait strategy (rows present = success), spinner as supplementary  
**Impact:** More reliable synchronization than waiting for spinner disappearance

#### 4. Party Role Ambiguity

**Challenge:** Grid doesn't label grantor vs grantee explicitly  
**Solution:** Deterministic positional mapping, clearly documented as non-legal  
**Impact:** Avoids incorrect legal assumptions while maintaining NC schema compatibility

#### 5. Large Result Sets

**Challenge:** Common names return 2000+ records across 60+ pages  
**Solution:** Runtime-based safety limits instead of page caps; detailed progress logging  
**Impact:** Allows legitimate large datasets while preventing infinite loops

### Edge Case Handling

| Edge Case | Handling Strategy | Implementation |
|-----------|------------------|----------------|
| **No results** | Wrapper with `tests[0].records = []`, `actual_count = 0` | Check for "No records" message or empty grid |
| **Network failures** | Retry with exponential backoff | Max 3 retries per operation |
| **Timeouts** | Per-page (60s) and total (1 hour) limits | Log clearly when limits trigger |
| **Missing fields** | Use `null` (not empty string/list) | Strict null assignment for unavailable data |
| **Parse errors** | Log warning, continue with next row | Graceful degradation per-row |
| **Last page detection** | Check "Pg X of Y" and Next button state | Multiple detection methods for robustness |

### Test Results Summary

**Test Cases (run via `--run-tests`):**

| # | Test Name | Expected | Actual | Pages | Status |
|---|-----------|----------|--------|-------|--------|
| 1 | Smith john jr | 16 | 16 | 1 | ✅ PASS |
| 2 | Smith john C | 81 | 81 | 3 | ✅ PASS |
| 3 | XYZ ABC | 0 | 0 | 0 | ✅ PASS |

**Validations performed per test:**
- Count match (actual == expected)
- Schema keys (exact 14 NC-schema fields)
- Null rules (parcel_number, doc_category, book_type, consideration must be null)
- Uppercase names (grantors/grantees)
- Date format (ISO 8601 with timezone offset)
- No URLs in data (document links not retrieved)

Execution progress is visible via stdout logs (no additional output files).

**Run the test suite:**
```bash
python src/seminole_scraper.py --run-tests
# Output: outputs/seminole_test_results.json (contains all 3 tests with validations)
```

### Usage

#### Command-Line Interface

```bash
# Run the full test suite (3 predefined test cases)
python src/seminole_scraper.py --run-tests

# Single name search
python src/seminole_scraper.py --name "SMITH JOHN"

# Headless mode (no browser window)
python src/seminole_scraper.py --name "SMITH JOHN" --headless

# Headless test suite
python src/seminole_scraper.py --run-tests --headless
```

> **Note:** The `--output` argument exists for backwards compatibility but is **ignored**. Output is always written to `outputs/seminole_test_results.json`.

#### Python API

The recommended usage is via CLI, which always writes the wrapper JSON to `outputs/seminole_test_results.json`. The scraper internally extracts NC-schema records from the Seminole County grid.

```python
# Direct API usage (advanced):
from seminole_scraper import SeminoleScraper

scraper = SeminoleScraper(headless=True)
try:
    records = scraper.search_by_name("SMITH JOHN")  # internal extraction
finally:
    scraper.close()
```

> **Note:** For evaluation, use the CLI (`--name` or `--run-tests`) which produces the standardized wrapper output.

### Output Format (Single Output File)

**File:** `outputs/seminole_test_results.json` — the **ONLY** output artifact for Task 2.

**Top-level structure:** Always a JSON **object wrapper** (never a plain array), containing:
- `generated_at` — ISO 8601 timestamp with timezone
- `county`, `state` — metadata
- `tests` — array of test/search runs
- `summary` — aggregated pass/fail counts

> **Clarification:** The assignment requirement "same JSON format as NC dataset" refers to **each record** inside `tests[].records[]`, not the top-level wrapper.

---

#### Example A: Single Search Mode (`--name "SMITH BROWN"`)

```json
{
  "generated_at": "2026-01-28T12:34:56-05:00",
  "county": "seminole",
  "state": "FL",
  "tests": [
    {
      "name": "SMITH BROWN",
      "expected_count": null,
      "actual_count": 1,
      "validations": {
        "count_match": true,
        "schema_keys_ok": true,
        "nulls_ok": true,
        "uppercase_names_ok": true,
        "date_timezone_ok": true,
        "no_links_ok": true,
        "errors": []
      },
      "records": [ /* 1 NC-schema record object */ ]
    }
  ],
  "summary": { "passed": 1, "failed": 0 }
}
```

- `tests` array contains **1 entry**
- `expected_count` is `null` (no predefined expectation for ad-hoc searches)

> **Validation note:** When `expected_count` is `null` (ad-hoc single searches), `count_match` is treated as N/A and reported as `true` to indicate no expectation-based failure occurred.

---

#### Example B: Test Suite Mode (`--run-tests`)

```json
{
  "generated_at": "2026-01-28T12:34:56-05:00",
  "county": "seminole",
  "state": "FL",
  "tests": [
    { "name": "Smith john jr", "expected_count": 16, "actual_count": 16, "validations": { "count_match": true, ... }, "records": [ /* 16 records */ ] },
    { "name": "Smith john C",  "expected_count": 81, "actual_count": 81, "validations": { "count_match": true, ... }, "records": [ /* 81 records */ ] },
    { "name": "XYZ ABC",       "expected_count": 0,  "actual_count": 0,  "validations": { "count_match": true, ... }, "records": [] }
  ],
  "summary": { "passed": 3, "failed": 0 }
}
```

- `tests` array contains **3 entries** (one per predefined test case)
- `expected_count` matches predefined values: 16, 81, 0
- `summary` aggregates all test results

---

#### Record Schema (NC-Compatible)

Each object in `tests[].records[]` has **exactly 14 keys** matching the NC dataset format:

```json
{
  "instrument_number": "20240012345",
  "parcel_number": null,
  "county": "seminole",
  "state": "FL",
  "book": "1234",
  "page": "567",
  "doc_type": "WARRANTY DEED",
  "doc_category": null,
  "original_doc_type": "WD",
  "book_type": null,
  "grantors": ["SMITH JOHN"],
  "grantees": ["JONES MARY"],
  "date": "2024-01-15T20:00:00-05:00",
  "consideration": null
}
```

- **14 exact keys** — no more, no less
- Fields not available on the Seminole website → `null`
- Names normalized to **UPPERCASE**
- Dates in **ISO 8601 with timezone offset** (e.g., `-05:00`)

### Why Extra Grid Columns Are Not Stored

The Seminole County results grid contains additional columns (e.g., "Description", "Verified Status") that have **no corresponding field in the NC schema**. These columns are intentionally NOT persisted because:

1. **Schema fidelity:** Output must match the NC dataset format exactly (14 keys)
2. **No schema extension:** We do not add extra keys beyond the NC specification
3. **Conservative approach:** If a field isn't in the target schema, we don't store it

We extract all columns needed to populate the NC schema fields. Columns without NC-schema mappings are read from the DOM but discarded during transformation.

### Logging & Debug Artifacts

**Logging:**
- All scraping activity is logged to **stdout (console)** at **INFO level**
- Includes: navigation, disclaimer handling, form fill, search click, grid ready, per-page pager status, pagination transitions, extracted counts, retries/timeouts, final RPM
- Log format: `[YYYY-MM-DD HH:MM:SS] [LEVEL] message`

**Debug Artifacts:**
- No debug artifacts are written by default

**Single Output File:**
- The **only** output artifact is `outputs/seminole_test_results.json`
- No supplementary files (e.g., no separate test_summary.json, no screenshots)

### Dependencies

**Required:**
- `selenium` - Browser automation for dynamic site interaction
- `webdriver-manager` - Automatic ChromeDriver management
- `pytz` - Timezone handling for ET/EST conversions
- `python-dateutil` - Flexible date parsing

**Notes:**
- Requires Chrome browser installed on system
- `webdriver-manager` downloads compatible ChromeDriver automatically
- Tested on Windows/Linux/macOS

### Performance Characteristics

> **Disclaimer:** All timings and RPM values below are example measurements from test runs. Actual performance will vary based on site response time, network latency, and system resources.

**Estimated Performance (Records Per Minute):**

| Metric | Formula |
|--------|---------|
| **N** | Number of extracted records |
| **t** | Elapsed time in seconds |
| **RPM** | `RPM = (N / t) × 60` (records/min) |
| **Runtime** | `t = (N × 60) / RPM` |

**Measured Test Runs:**

| Test Case | Records (N) | RPM | Runtime (t) |
|-----------|-------------|-----|-------------|
| Smith john jr | 16 | 20.2 | ~47.5s |
| Smith john C | 81 | 98.2 | ~49.5s |
| XYZ ABC | 0 | — | ~15s |

**Performance Model Analysis:**

The runtime follows: `t(N) = t₀ + αN`

Where:
- **t₀** = fixed overhead (browser init, disclaimer, search form, first page load)
- **α** = per-record marginal cost (extraction + pagination)

**Key Insight:** Since `t ≈ 48-49.5s` for both N=16 and N=81, the fixed overhead **t₀ dominates** and per-record cost **α is small**. This means:

```
RPM(N) = 60N / (t₀ + αN)
```

**RPM increases with N** due to overhead amortization — larger result sets are more efficient per-record.

**Practical Estimates:**
- Small result sets (<100 records): ~30-60 seconds
- Medium result sets (100-500 records): ~2-5 minutes  
- Large result sets (2000+ records): ~15-25 minutes

**Factors Affecting Performance:**
- Site response time (network latency)
- Result set size and pagination count
- Request delay (2s between pages for respectful scraping)

**Safety Limits:**
- Per-page timeout: 60 seconds
- Total runtime limit: 1 hour (configurable)
- No artificial page caps (scrapes all indicated pages)

---

**Last Updated:** January 2026  
**Status:** Tasks 1 & 2 complete

<!-- REPORT_START -->

### ✅ Task 3: Document Type Classification (COMPLETE)
**Script:** `src/llm_classifier.py`  
**Output:** `outputs/doc_type_mapping.json`  
**Objective:** Standardize messy `doc_type` values into 9 canonical categories using a multi-pass pipeline (Regex + LLM).

#### 📋 Task 3: Methodology & Report

## Coverage Metrics (Unique Doc Types — unweighted)
*These percentages are out of the 339 unique doc_type strings found in the dataset. Many rare/long-tail types may remain MISC.*
- **Non-MISC types**: 119 / 339 (35.1%)
- **MISC types**: 220 / 339 (64.9%)
- Breakdown by pass:
    - Resolved by Pass 1 (Rules): 95 (28.0%)
    - Resolved by Pass 2a (LLM): 15 (4.4%)
    - Resolved by Pass 2b (LLM+Proto): 9 (2.7%)

## Coverage Metrics (All Records — frequency-weighted by occurrence)
*These percentages are out of the 13,886 total records. A small set of very common doc_type values can cover most records even if many rare types are MISC.*
- **Non-MISC records**: 10983 / 13886 (79.1%)
- **MISC records**: 2903 / 13886 (20.9%)

> **Note on Metrics**: It’s normal for MISC to be high by unique types but low by records because MISC often contains many low-frequency (long-tail) values that have minimal impact on overall dataset coverage.

## LLM Usage & Estimated Cost
- Total LLM Calls: 10
- Prompt Tokens: 5925
- Completion Tokens: 15507
- Estimated Cost: $0.0102 (using assumed GPT-4o-mini rates; verify current pricing)

## Top Unresolved by Frequency (After Pass 1)
- `CANCELLATION` (203 records)
- `ASSIGNMENT` (193 records)
- `SUBSTITUTION TRUSTEE` (165 records)
- `SEE INSTRUMENT` (162 records)
- `CAN` (138 records)
- `POWER OF ATTORNEY` (132 records)
- `AFFIDAVIT` (100 records)
- `FORECLOSURE` (95 records)
- `SUB TR` (82 records)
- `D OF T` (78 records)
- `MISCELLANEOUS` (75 records)
- `REL D` (65 records)
- `ESMT` (56 records)
- `Restrictions` (54 records)
- `UNIFORM COMMERCIAL CODE` (52 records)

## Methodology
1. **Pass 1 (High-Precision Rules)**: Regex-based matching. Ambiguous matches (multiple categories) are deferred.
2. **Pass 2a (LLM Batch)**: GPT-4o-mini classification accepting only certainty='HIGH'.
3. **Pass 2b (LLM Calibration)**: GPT-4o-mini with canonical prototypes accepting certainty in ['HIGH', 'MEDIUM'].
4. **Fallback**: Anything below thresholds or invalid is mapped to MISC.

<!-- REPORT_END -->
