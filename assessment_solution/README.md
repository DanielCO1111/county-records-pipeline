# 📊 Dono Data Engineer Assessment

> **Solution repository for the Dono Data Engineering take-home assignment**

---

## 📋 Tasks Overview

### ✅ Task 1: County Pattern Analysis (COMPLETE)
**Script:** `src/pattern_analyzer.py`  
**Output:** `outputs/county_patterns.json`  
**Objective:** Extract and document patterns in instrument numbers, book/page numbers, date ranges, and document types for each of the 13 NC counties.

### 🔜 Task 2: TBD
(To be implemented)

---

## 📁 Project Structure

```
assessment_solution/
├── src/
│   └── pattern_analyzer.py      # Task 1: County pattern analysis
├── outputs/
│   └── county_patterns.json     # Task 1: Generated analysis results
├── requirements.txt              # Python dependencies
├── pyproject.toml               # Code formatting/linting configuration
└── README.md                    # This file

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
pandas          # Data manipulation (available but not required for pattern_analyzer.py)
python-dateutil # Robust date parsing (installed but ISO-strict parsing used)
tqdm            # Progress bars (not used in current implementation)
requests        # HTTP requests (not used in pattern analyzer)
beautifulsoup4  # HTML parsing (not used in pattern analyzer)
lxml            # XML processing (not used in pattern analyzer)
```

**Note:** The pattern analyzer (`src/pattern_analyzer.py`) uses only Python standard library features for core functionality. External dependencies are available but not utilized in the current implementation to maintain simplicity and minimize dependencies.

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
```

**Expected:** Processes 13,886 records in 5-10 seconds.

---

**Last Updated:** January 2026  
**Status:** Task 1 complete, ready for Task 2
