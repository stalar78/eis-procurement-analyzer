# Architecture

## Purpose

EIS Procurement Analyzer now contains two cooperating layers:

1. the original local document-analysis pipeline;
2. EIS Procurement Radar, a stateful orchestration layer for live discovery, historical competition intelligence, selective enrichment, and manual decision support.

The Radar uses SQLite for local state and caching but does not require a web service or external database server.

## High-level architecture

```text
Public EIS
    |
    +--> live search/discovery
    |      -> status/deadline normalization
    |      -> open verification
    |      -> preliminary scoring
    |
    +--> completed-procurement search
    |      -> historical candidate discovery
    |      -> category/similarity selection
    |      -> result/protocol extraction
    |      -> competition metrics
    |
    +--> selected live procurement
           -> controlled document collection
           -> artifact registry
           -> document analyzer
           -> deep assessment

All stages
    -> SQLite state/cache
    -> structured reports
    -> manual review
```

## 1. Legacy collection and analyzer entry points

The existing scripts remain usable independently:

- `collect_results.py` — EIS search-result collection;
- `score_results.py` — lightweight ranking;
- `collect_candidate_details.py` — procurement section traversal and document collection;
- `analyze_candidate_documents.py` — extraction, classification, evidence, technical/market assessment, and reports.

Radar reuses these layers through importable compatibility APIs rather than duplicating document-collection and analysis logic.

## 2. Radar orchestration

`radar.runner` is the CLI/orchestration entry point.

Its responsibilities include:

- configuration and profile loading;
- discovery mode selection;
- card/state handling;
- provisional assessment;
- optional historical intelligence;
- optional document enrichment;
- transactional reporting.

The current Radar version is exposed from `radar.__init__`.

## 3. Live discovery

Main modules:

- `radar.discovery`
- `radar.search_request`
- `radar.search_profiles`
- `radar.open_verification`
- `radar.prefilter`
- `radar.scoring`

Discovery builds explicit EIS search requests, preserves filters during pagination, normalizes status/deadline evidence, deduplicates cards, and optionally verifies the current open state from the procurement detail page.

Query/page/card budgets prevent uncontrolled crawling.

## 4. State

`radar.state` provides SQLite-backed local state for runs, procurement observations, assessments, enrichment state, historical state, artifacts, and recovery metadata.

State supports:

- new/changed detection;
- cache reuse;
- resumable workflows;
- version-aware analysis reuse;
- last-known-good source information.

The SQLite database is runtime data and is excluded from Git.

## 5. Historical intelligence

Main modules:

- `radar.historical`
- `radar.analog_search`
- `radar.competition_metrics`
- `radar.customer_history`
- `radar.supplier_history`
- `radar.dumping_risk`
- `radar.result_extraction`
- `radar.historical_live_validation`

The historical flow searches bounded sets of completed procurements, scores category/similarity compatibility, resolves public result/protocol evidence, assembles usable result fields, and calculates competition metrics with explicit confidence.

Historical assessments are stored separately from preliminary and deep assessments.

## 6. Analog selection

`radar.analog_search` performs source-aware query and similarity work.

Important design properties:

- Russian text normalization and mojibake repair;
- source-specific functional terms;
- term-importance weighting;
- category compatibility before relaxed similarity;
- explicit score components;
- bounded fallback selection modes.

The objective is to prefer no sample over an irrelevant sample.

## 7. Historical result extraction

`radar.result_extraction` handles 44-FZ and 223-FZ public result/protocol paths separately.

Competition fields may be assembled from multiple pages/documents for one procurement. Field provenance is retained.

Partial results can contribute independently to participant, reduction, and winner samples rather than requiring one fully complete analog record.

## 8. Live enrichment

Main modules:

- `radar.enrichment`
- `radar.live_collection`
- `radar.artifact_registry`
- `radar.deep_assessment`

Enrichment selects bounded live candidates, traverses procurement sections, validates downloads, registers artifacts, invokes the existing document analyzer, and maps its structured result into a deep Radar assessment.

## 9. Source resilience

`radar.source_resolution` handles unstable EIS URLs using bounded strategies such as:

- supplied URL;
- last-known-good URL;
- exact-number search recovery;
- alternate-section recovery;
- cached source snapshots.

A single failed request is not treated as definitive disappearance when other evidence exists.

## 10. Reporting

`radar.reporting` writes structured JSON/CSV/XLSX/Markdown outputs for discovery, assessments, historical metrics, enrichment, and diagnostics.

Real-run publication is transactional: per-run artifacts are created first, then `latest.*` is updated only according to run-quality rules. `latest_attempt.json` can preserve the most recent attempt independently from the latest publishable result.

## 11. Original document extraction

`analyze_candidate_documents.py` continues to handle local procurement corpora.

Supported paths include DOCX/DOC, PDF, XLSX/XLS, ZIP/RAR, RTF, TXT, HTML, and selected binary fallbacks. Optional local utilities may improve legacy-format coverage.

Document classification and strict extraction continue to enforce allowed-source rules for important facts and financial values.

## 12. Source-dependent vs reusable layers

Source-dependent responsibilities include:

- EIS search parameters and selectors;
- card/section navigation;
- result/protocol layout handling;
- attachment discovery and request behavior.

Reusable analytical concepts include:

- artifact hashing and manifests;
- document extraction/classification;
- evidence provenance;
- conflict/quality states;
- similarity components;
- competition aggregation;
- scoring and reporting;
- stateful cache/resume patterns.

Supporting another procurement source would require a new source adapter and validation. The repository does not claim universal connector support.

## 13. Repository boundary

The public repository contains source code, configuration examples, tests, and synthetic/test-oriented fixtures.

The following remain local runtime data:

- live procurement documents;
- EIS HTML snapshots;
- result/protocol downloads;
- SQLite state;
- generated reports;
- browser authentication/storage state;
- caches and temporary run directories.
