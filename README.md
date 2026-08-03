# EIS Procurement Analyzer

EIS Procurement Analyzer is a rule-based Python pipeline for collecting, downloading, classifying, and analyzing public procurement materials from the Russian EIS system.

The project is designed to turn fragmented search cards, technical specifications, contract drafts, protocols, price calculations, and clarifications into structured, evidence-backed data for manual decision support.

It is not a legal, financial, or automated participation service. Final decisions always require independent human review.

## What the project demonstrates

- browser automation with Playwright;
- paginated collection with retries, delays, deduplication, and checkpoints;
- procurement-card traversal and attachment discovery;
- defensive document downloads with `Content-Type` and `Content-Disposition` checks;
- protection against saving HTML responses as documents;
- extraction from DOCX, DOC, PDF, XLSX, XLS, ZIP, RAR, RTF, TXT, HTML, and BIN sources;
- document classification by filename, section, content, and score-based rules;
- strict financial extraction that prefers missing values over unsupported guesses;
- evidence records with source, document type, excerpt, location, method, and confidence;
- conflict detection and data-quality reporting;
- separate technical, market, and overall recommendation layers;
- Excel, CSV, JSON, and Markdown outputs;
- regression tests for strict extraction and decision gates.

## Pipeline

```text
EIS search results
    -> collection and deduplication
    -> rule-based candidate filtering
    -> procurement-card traversal
    -> document download and manifest
    -> text and table extraction
    -> document classification
    -> strict field extraction
    -> evidence and conflict checks
    -> technical and market assessment
    -> Excel / CSV / JSON / Markdown reports
```

Detailed descriptions:

- [Architecture](docs/ARCHITECTURE.md)
- [Methodology](docs/METHODOLOGY.md)
- [Outputs](docs/OUTPUTS.md)
- [Synthetic examples](examples/README.md)
- [Security policy](SECURITY.md)

## Main scripts

- `collect_results.py` — collects search-result cards and writes local datasets.
- `score_results.py` — applies lightweight rule-based scoring and ranking.
- `collect_candidate_details.py` — traverses procurement sections, saves page material, discovers attachments, and optionally downloads documents.
- `analyze_candidate_documents.py` — extracts content, classifies documents, builds evidence, calculates heuristic scores, and writes reports.

The current analyzer model is identified in code and reports as `2.2-decision-model`.

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

Optional local tools improve extraction quality for legacy formats:

- LibreOffice for older Office documents;
- 7-Zip or `unrar` for RAR archives;
- `antiword` for older `.doc` files.

Dependency versions are not yet locked. Reproducibility and CI hardening are planned as a separate controlled step.

## Safe validation

The repository includes regression tests and synthetic fixtures. The following checks do not require live EIS collection:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The built-in regression mode is also available:

```powershell
.\.venv\Scripts\python.exe .\analyze_candidate_documents.py --run-regression-tests
```

Run collection commands only after reviewing source rules, request limits, and the local output location.

## Live collection commands

Example: collect a limited number of result pages.

```powershell
.\.venv\Scripts\python.exe .\collect_results.py --max-pages 2 --headless
```

Example: traverse selected candidates without downloading attachments.

```powershell
.\.venv\Scripts\python.exe .\collect_candidate_details.py --input all_web_tenders_classified.xlsx --limit 5 --headless
```

Example: download candidate documents.

```powershell
.\.venv\Scripts\python.exe .\collect_candidate_details.py --input all_web_tenders_classified.xlsx --limit 5 --download --headless
```

Example: analyze an existing local candidate directory.

```powershell
.\.venv\Scripts\python.exe .\analyze_candidate_documents.py --input candidate_details --output candidate_analysis --limit 5 --overwrite --verbose
```

These commands access live or locally generated material. Generated data must remain outside the public repository.

## Supported source formats

The analyzer currently handles text extraction or structured parsing for:

- `.docx` and `.doc`;
- `.pdf`;
- `.xlsx` and `.xls`;
- `.zip` and `.rar`;
- `.rtf`;
- `.txt`;
- `.html` and `.htm`;
- `.bin` when a supported signature or fallback path is available.

Quality depends on source readability and optional local utilities.

## Confirmed development-run scale

Local project artifacts confirm the following aggregate development-run figures:

- 1,237 unique collected procurement records;
- 15 selected candidates in the detailed research queue;
- 125 downloaded documents;
- at least one result marked for manual review because of an extreme price reduction.

Only aggregate figures are published. Real procurement documents, local datasets, customer names, procurement identifiers, and generated reports are intentionally excluded from this repository.

Claims about more than 50 participants or confirmed conflicts between technical specifications and clarifications are not used because the current audited artifacts do not confirm them.

## Decision model

The analyzer separates three questions:

1. `technical_participation_verdict` — whether the documented scope appears technically feasible under the model.
2. `market_result_status` — whether protocol and result data are available and suitable for market interpretation.
3. `overall_recommendation` — a combined heuristic priority for manual review.

These statuses are decision-support signals, not automated legal or financial conclusions.

## Public examples

All tracked examples under `examples/` are synthetic. They use fictional organizations, invalid domains, and invented procurement identifiers.

Do not replace them with real downloaded documents or generated local reports.

## Known limitations

- The current implementation is deterministic and does not call external LLM APIs.
- Classification, scoring, and price recommendations are heuristic.
- OCR is optional and depends on local tooling.
- Some EIS pages and documents may be unavailable, malformed, duplicated, or encoded inconsistently.
- Legacy Office and archive extraction quality depends on installed utilities.
- Source selectors and download behavior may need maintenance when the external platform changes.
- The project does not bypass CAPTCHA, authentication boundaries, or closed access.
- The repository is not a production SaaS and does not provide automatic participation decisions.

## Possible future development

Future directions may include scheduled monitoring, notifications, source adapters, version comparison, semantic search, a review interface, and team workflows.

These are roadmap directions, not current features.

## License

MIT License. See [LICENSE](LICENSE).
