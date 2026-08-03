# EIS Procurement Analyzer

Technical README draft for a future public portfolio repository by Stalar Vision.

## Purpose

EIS Procurement Analyzer collects, downloads, normalizes, and performs deterministic rule-based analysis of Russian public procurement materials from EIS. The project is designed to inspect web/software-related procurements, extract evidence-backed fields, classify documents, evaluate technical participation feasibility, and produce local analysis reports.

The current analyzer version is `2.2-decision-model`.

## Main Scripts

- `collect_results.py`: collects procurement cards from an EIS search results page and writes local datasets under `data/`.
- `score_results.py`: applies lightweight scoring to collected search results and produces a ranked spreadsheet.
- `collect_candidate_details.py`: opens selected procurement cards, saves page text/HTML, discovers attachment links, and optionally downloads documents.
- `analyze_candidate_documents.py`: extracts text from downloaded documents, classifies document types, applies strict financial extraction, builds evidence, and writes analysis reports.

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

Optional local tools improve extraction quality for some document formats:

- LibreOffice for legacy Office documents.
- 7-Zip or unrar for archives.
- antiword for old `.doc` files.

## Current Commands

Collect search results:

```powershell
.\.venv\Scripts\python.exe .\collect_results.py --max-pages 2 --headless
```

Collect candidate details without downloads:

```powershell
.\.venv\Scripts\python.exe .\collect_candidate_details.py --input all_web_tenders_classified.xlsx --limit 5 --headless
```

Collect candidate details with document downloads:

```powershell
.\.venv\Scripts\python.exe .\collect_candidate_details.py --input all_web_tenders_classified.xlsx --limit 5 --download --headless
```

Analyze downloaded candidate documents:

```powershell
.\.venv\Scripts\python.exe .\analyze_candidate_documents.py --input candidate_details --output candidate_analysis --limit 5 --overwrite --verbose
```

Run built-in regression checks:

```powershell
.\.venv\Scripts\python.exe .\analyze_candidate_documents.py --run-regression-tests
```

Run tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## CLI Arguments

`collect_results.py` supports:

- `--url`
- `--output`
- `--start-page`
- `--max-pages`
- `--records-per-page`
- `--delay-min`
- `--delay-max`
- `--timeout`
- `--retries`
- `--headless`
- `--force`

`collect_candidate_details.py` supports:

- `--input`
- `--sheet`
- `--output`
- `--limit`
- `--delay`
- `--download`
- `--download-timeout`
- `--retries`
- `--overwrite`
- `--headless`
- `--zip`

`analyze_candidate_documents.py` supports:

- `--input`
- `--output`
- `--procurement-number`
- `--limit`
- `--overwrite`
- `--skip-ocr`
- `--verbose`
- `--run-regression-tests`

## Supported Input Formats

The analyzer currently handles text extraction or structured parsing for:

- `.docx`
- `.doc`
- `.pdf`
- `.xlsx`
- `.xls`
- `.zip`
- `.rar`
- `.rtf`
- `.txt`
- `.html`
- `.htm`
- `.bin`

Quality depends on available local utilities and source document readability.

## Output Structure

The analyzer writes outputs to the selected analysis directory, for example `candidate_analysis/`:

- `procurement_analysis.xlsx`
- `procurement_analysis.json`
- `procurement_analysis.csv`
- `extraction_manifest.csv`
- `document_classification.csv`
- `evidence_index.csv`
- `unresolved_fields.csv`
- `quality_issues.csv`
- `field_conflicts.csv`
- `rejected_candidates.csv`
- `analysis_summary.md`
- per-procurement analysis folders with extracted text and evidence files

These outputs are generated local data and must not be committed to a public repository.

## Known Limitations

- The project is deterministic and does not call external LLM APIs.
- OCR is optional and depends on local tooling.
- Some public EIS pages and documents can be unavailable, malformed, duplicated, or encoded inconsistently.
- Strict financial extraction intentionally prefers missing values over unsupported inferred values.
- Participation recommendations are heuristic and require manual legal, financial, and technical review.
- Public examples in `examples/` are synthetic and do not represent real procurement data.
