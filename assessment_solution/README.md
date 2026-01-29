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

### ✅ Task 3: Document Type Classification (COMPLETE)
**Script:** `src/llm_classifier.py`  
**Output:** `outputs/doc_type_mapping.json`  
**Objective:** Standardize messy `doc_type` values into 9 canonical categories using a multi-pass pipeline (Regex + LLM).

---

## 📁 Project Structure

```
assessment_solution/
├── src/
│   ├── pattern_analyzer.py       # Task 1: County pattern analysis
│   ├── seminole_scraper.py       # Task 2: FL county scraper (includes --run-tests)
│   └── llm_classifier.py         # Task 3: LLM-based doc_type classification
├── outputs/
│   ├── county_patterns.json      # Task 1: Analysis results
│   ├── seminole_test_results.json # Task 2: Scraped FL records
│   └── doc_type_mapping.json     # Task 3: Standardized mapping
├── requirements.txt               # Python dependencies
├── pyproject.toml                # Code formatting/linting configuration
└── README.md                     # This file
```

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

# Task 3 (LLM Classifier) - REQUIRED
openai            # OpenAI API client
python-dotenv     # Environment variable management

# Optional / Development only
pandas            # Data manipulation (optional)
tqdm              # Progress bars (optional)
black             # Code formatter (dev)
ruff              # Python linter (dev)
```

**Note:** 
- Task 1 (`pattern_analyzer.py`) uses only Python standard library
- Task 2 (`seminole_scraper.py`) requires: `selenium`, `webdriver-manager`, `pytz`, `python-dateutil`
- Task 3 (`llm_classifier.py`) requires: `openai`, `python-dotenv`

---

## 🚀 Setup Instructions

### 1️⃣ Create Virtual Environment

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

## 💻 Usage

### Task 3: Document Type Classification

**Objective:** Standardize messy `doc_type` values into 9 canonical categories.

**Run the script:**
```bash
cd assessment_solution
# Ensure OPENAI_API_KEY is set in .env or environment
python src/llm_classifier.py
```

**Output:** `outputs/doc_type_mapping.json`

---

## 📋 Task 3: Methodology & Report

### Classification Pipeline: "Rules-first + LLM with Calibration"

1. **Pass 1 (High-Precision Rules)**: 
   - Uses regex to match obvious document types (e.g., `DEED` -> `SALE_DEED`).
   - **Ambiguity Handling**: If a string matches multiple categories (e.g., "RELEASE OF LIEN"), it is marked as unresolved to avoid incorrect guesses.
   - No `MISC` labels are assigned in this pass.

2. **Pass 2a (LLM Batch Classification)**:
   - Unresolved types are sent to GPT-4o-mini in batches.
   - **Strict Guardrails**: JSON-only output, numeric confidence scores.
   - **Threshold**: Only results with `confidence >= 0.85` are accepted.

3. **Pass 2b (LLM Prototype Calibration)**:
   - Low-confidence items from Pass 2a are re-evaluated with "prototypes" (canonical examples like `PLAT: map, survey`).
   - **Threshold**: `confidence >= 0.85`.

4. **Final Fallback**:
   - Any items still unresolved or below thresholds are mapped to `MISC`.

### Coverage Metrics (Sample Run)

- **Total Unique Doc Types**: 339
- **Resolved by Pass 1 (Rules)**: 74 (21.8%)
- **Resolved by Pass 2a (LLM)**: *[Requires API Key]*
- **Resolved by Pass 2b (LLM+Proto)**: *[Requires API Key]*
- **Finalized as MISC**: 265 (78.2% - *Fallback without API Key*)

**Frequency-Weighted Coverage (Total Records - 13,886)**:
- **Non-MISC Coverage**: 58.7% (Base rules only)
- **MISC Coverage**: 41.3%

---

**Last Updated:** January 2026  
**Status:** Tasks 1, 2, & 3 complete
