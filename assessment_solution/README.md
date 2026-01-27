# 📊 Dono Data Engineer Assessment

> **Solution repository for the Dono Data Engineering take-home assignment**

---

## 📁 Project Structure

```
assessment_solution/
├── src/              # Source code implementation
├── outputs/          # Generated results and deliverables
├── requirements.txt  # Python dependencies
├── pyproject.toml    # Code formatting/linting configuration
└── README.md         # This file

../
├── nc_records_assessment.jsonl  # Input data (JSONL format, ~14K records)
└── records/                     # PDF files organized by county/instrument_number.pdf
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

### Running the Pattern Analyzer

From the project root directory:

```bash
# Navigate to assessment solution directory
cd assessment_solution

# Run the pattern analyzer
python src/pattern_analyzer.py
```

The script will:
1. ✅ Read `nc_records_assessment.jsonl` (from parent directory)
2. ✅ Process all ~13,886 records using streaming (line-by-line)
3. ✅ Generate `outputs/county_patterns.json` with analysis results
4. ✅ Display progress updates every 1,000 records
5. ✅ Report total records processed and any errors

**Expected Output:**
```
Reading records from: .../nc_records_assessment.jsonl
Processing records (streaming mode)...
Processed 13886 records (0 errors)
Generating pattern analysis...
Writing results to: .../outputs/county_patterns.json

============================================================
PATTERN ANALYSIS COMPLETE
============================================================
Counties analyzed: 13
Total records: 13886
Output file: .../outputs/county_patterns.json
============================================================
```

**Performance:**
- Processing time: ~5-10 seconds on modern hardware
- Memory usage: < 100MB (streaming design)
- No external dependencies beyond Python standard library + requirements.txt

---

## 📝 Data Format

### Input: `nc_records_assessment.jsonl`
- **Format:** JSONL (one JSON record per line)
- **Records:** ~13,887 entries
- **Structure:** Each line contains a JSON object with record metadata

### Input: `records/`
- **Format:** PDF files
- **Organization:** `county/instrument_number.pdf`
- **Counties:** alamance, buncombe, cabarrus, cumberland, davidson, durham, forsyth, guilford, johnston, mecklenburg, onslow, union, wake

---

## 📦 Outputs

Generated results and deliverables will be saved to:
```
assessment_solution/outputs/
```

---

## 📋 Key Assumptions & Design Decisions

> **Critical for Testers:** These assumptions were made based on requirements analysis and data inspection.

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

## 🧪 For Project Testers

### What to Verify

1. **Output Schema Compliance:**
   - All 13 counties present in output
   - Required fields: `record_count`, `instrument_patterns`, `book_patterns`, `page_patterns`, `date_range`, `doc_type_distribution`, `unique_doc_types`, `doc_type_to_category_mapping`
   - Pattern objects have: `pattern`, `regex`, `example`, `count`, `percentage`
   - Ranges present for numeric patterns

2. **Data Accuracy:**
   - Anomaly counts represent total occurrences (not just examples)
   - Percentages sum to ~100% (of non-null values)
   - Ranges are family-specific (different for different pattern types)
   - Top 10 doc_types only (not full distribution)

3. **Pattern Quality:**
   - Regex patterns match their descriptions
   - Examples are real values from dataset
   - Top patterns capture majority of records (>90%)
   - "other" bucket is small (<10%)

4. **Edge Cases Handled:**
   - `bp` prefix synthetic IDs classified separately
   - Null values counted separately (not in patterns)
   - Zero-padded merged when < 5%
   - Mixed year-letter values (e.g., `20240091879C`) in alphanumeric, not year_prefixed

### Known Limitations

1. **Single-pass processing** - Cannot make multiple passes over data
2. **ISO date parsing only** - Non-ISO dates flagged as unparseable (intentional for data quality)
3. **No PDF analysis** - Only analyzes JSONL metadata, not PDF contents
4. **Memory-efficient trade-offs** - Caps examples at 5-20 per pattern

### Troubleshooting

**"File not found" error:**
- Ensure `nc_records_assessment.jsonl` is in parent directory (one level up from `assessment_solution/`)

**"No module named X" error:**
- Run `pip install -r requirements.txt` in virtual environment

**Unexpected pattern classifications:**
- Review classification precedence order (section 1 above)
- Check if values match strict format definitions (digits-only for year patterns)

---

## 🚀 Quick Start (For Testers)

**Complete workflow from scratch:**

```bash
# 1. Clone/extract project
cd Dono_DataEngineering_Assessment/assessment_solution

# 2. Create virtual environment
python -m venv .venv

# 3. Activate virtual environment
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# Linux/macOS:
source .venv/bin/activate

# 4. Install dependencies
python -m pip install -U pip
python -m pip install -r requirements.txt

# 5. Run pattern analyzer
python src/pattern_analyzer.py

# 6. Check output
cat outputs/county_patterns.json  # Linux/macOS
type outputs\county_patterns.json  # Windows
```

**Expected runtime:** 5-10 seconds  
**Expected output size:** ~60 KB JSON file

### Testing Checklist

- [ ] Script completes without errors
- [ ] Output file created at `outputs/county_patterns.json`
- [ ] All 13 counties present in output
- [ ] Each county has all required fields
- [ ] Anomaly counts > examples (for null_date, usually 20-30 total vs 5 examples)
- [ ] Ranges different for different pattern families
- [ ] doc_type_distribution has exactly 10 entries per county
- [ ] Progress indicator displays during processing
- [ ] Final summary shows 13,886 records processed

---

**Last Updated:** January 2026
