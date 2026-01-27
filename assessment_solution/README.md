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

- **Python:** 3.9 or higher
- **Tested on:** Python 3.13
- **Platform:** Windows/Linux/macOS

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

### Data Processing

The scripts process the large JSONL input file using **streaming** (line-by-line) to avoid loading the entire dataset into memory.

```bash
# Commands will be added once implementation is complete
```

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

**Last Updated:** January 2026
