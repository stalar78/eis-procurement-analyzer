# Architecture

## Purpose

EIS Procurement Analyzer is organized as a local multi-stage pipeline. Each stage produces explicit files that can be inspected, resumed, or passed to the next stage.

The project does not require a database or web service in its current form.

## High-level flow

```text
Public EIS search pages
    -> collect_results.py
    -> local search datasets and checkpoints
    -> score_results.py
    -> ranked candidate dataset
    -> collect_candidate_details.py
    -> page captures, links, download manifest, documents
    -> analyze_candidate_documents.py
    -> extracted content, classifications, evidence, scores, reports
```

## 1. Search collection

`collect_results.py` uses Playwright to open search-result pages and collect procurement cards.

Responsibilities:

- open the configured public search URL;
- move through result pages;
- apply conservative delays and retry behavior;
- extract procurement metadata and source text;
- preserve the search query that found each record;
- deduplicate records;
- save checkpoints for partial recovery;
- export local CSV, XLSX, and JSON datasets.

The collector depends on the current external page structure. Selectors and navigation logic may require maintenance when EIS changes.

## 2. Initial scoring

`score_results.py` performs lightweight rule-based classification over the collected search dataset.

It is intended to distinguish likely development or modernization work from licenses, equipment, education, access to ready-made software, and unrelated results.

This stage narrows the research set. It does not replace detailed document analysis.

## 3. Candidate traversal and downloads

`collect_candidate_details.py` opens selected procurement cards and traverses available sections such as general information, documents, results, events, contracts, protocols, and clarifications.

It records page text, HTML, discovered links, section metadata, and processing logs.

The download layer uses defensive checks:

- Playwright browser context;
- request/API context where applicable;
- cookies and request headers from the browser session;
- redirects;
- `requests` fallback;
- retries for transient statuses;
- `Content-Type` inspection;
- `Content-Disposition` filename extraction;
- file-extension inference;
- rejection of HTML responses presented as attachments;
- a download manifest containing URL, status, type, size, and error details.

No access boundary is bypassed. The current design is for publicly available material.

## 4. Document extraction

`analyze_candidate_documents.py` processes the downloaded local corpus.

Supported paths include:

- DOCX and DOC;
- PDF;
- XLSX and XLS;
- ZIP and RAR;
- RTF;
- TXT;
- HTML;
- selected binary fallbacks.

Extraction may use optional local tools such as LibreOffice, 7-Zip, `unrar`, or `antiword`. Missing tools reduce extraction coverage but should not silently convert an unreadable file into a missing file.

Archives are handled through dedicated extraction paths. The analyzer records extraction status and quality information for each source.

## 5. Document classification

Documents are classified using multiple signals:

- filename;
- procurement-card section;
- extracted text;
- stable phrases;
- score-based rules.

Current categories include technical specifications, technical attachments, contract drafts, signed contracts, NMCK calculations, application requirements, information cards, clarifications, protocols, notices, bank details, signatures, and other files.

The result is written to `document_classification.csv` and used by strict extraction rules.

## 6. Strict extraction and evidence

Important fields are extracted only from allowed document types.

Examples:

- final price from a final protocol or signed contract;
- participant count from a protocol;
- functionality from technical specifications and clarifications;
- application requirements from the corresponding requirements or information card;
- acceptance and rights from contract and technical documents.

Every important accepted value can be accompanied by evidence metadata:

- source file;
- document type;
- page, sheet, or cell reference where available;
- excerpt;
- extraction method;
- confidence.

Unsupported candidates can be rejected rather than promoted to final values.

## 7. Decision model

The analyzer keeps technical feasibility separate from market evidence.

Main layers:

- `technical_participation_verdict`;
- `market_result_status`;
- `overall_recommendation`.

This prevents a technically feasible scope from being treated as economically attractive when protocols are missing, contradictory, or show extreme price reduction.

Scores and verdicts are heuristic. They are inputs to manual review, not automatic participation decisions.

## 8. Reporting

The final stage writes structured outputs for different review tasks:

- consolidated workbook;
- CSV and JSON exports;
- document and extraction manifests;
- evidence index;
- unresolved fields;
- quality issues;
- field conflicts;
- rejected candidates;
- Markdown summary;
- per-procurement extracted material.

Generated outputs and real downloaded documents are deliberately ignored by Git and must remain local.

## Source-dependent and reusable layers

The current code is EIS-specific, but its responsibilities can be viewed in two groups.

### Source-dependent

- navigation and selectors;
- pagination;
- card structure;
- section URLs;
- attachment discovery;
- source-specific request behavior.

### Reusable analytical concepts

- local document storage;
- format detection;
- text and table extraction;
- document classification;
- evidence records;
- conflict detection;
- quality states;
- scoring and reporting.

Supporting another source would require separate analysis and implementation. The repository does not currently claim universal connector support.
