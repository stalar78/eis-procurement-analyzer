# EIS Procurement Analyzer

EIS Procurement Analyzer is a rule-based Python pipeline for collecting, downloading, classifying, and analyzing public procurement materials from the Russian EIS system.

The repository now includes **EIS Procurement Radar**: a stateful decision-support layer that discovers currently active procurements, verifies whether applications are still open, estimates technical fit, enriches selected candidates with procurement documents, searches historical analogs, extracts competition evidence from result/protocol pages, and produces explainable risk-adjusted recommendations.

The project is designed for manual decision support. It is **not** a legal, financial, automated bidding, or automated participation service.

## Current status

- Radar version: `0.3.4-r3a-result-extraction`
- Historical result extraction version: `0.3.4-r3a-result-extraction`
- Test suite at the current milestone: `131 passed`
- R3A historical intelligence is ready for **controlled recurring use** with explicit confidence and bounded online collection.

The historical layer is intentionally conservative: missing evidence remains missing, partial result data can contribute only to the metrics it actually supports, and low-confidence market signals must not be treated as precise predictions.

## What the project demonstrates

- Playwright-based EIS discovery and page traversal;
- active-procedure search with explicit stage filters and deadline verification;
- status normalization and detail-page open verification;
- SQLite-backed run, observation, enrichment, and historical state;
- new/changed procurement detection and resumable processing;
- controlled document enrichment with download budgets and artifact hashing;
- defensive downloads with content-type, signature, and HTML-response checks;
- extraction from DOCX, DOC, PDF, XLSX, XLS, ZIP, RAR, RTF, TXT, HTML, and selected binary sources;
- document classification and evidence-backed strict field extraction;
- deep technical assessment separated from market evidence;
- source recovery and last-known-good caching for unstable EIS URLs;
- bounded historical analog search with explainable rule-based similarity;
- source-aware Russian query normalization and category gating;
- 44-FZ and 223-FZ result/protocol resolution paths;
- multi-document historical result assembly;
- separate participant, price-reduction, and winner sample sizes;
- competition metrics, historical confidence, and dumping-risk signals;
- transactional reporting with `latest` vs `latest_attempt` semantics;
- Excel, CSV, JSON, and Markdown outputs;
- regression tests for discovery, enrichment, state, analog selection, result extraction, and decision gates.

## Radar pipeline

```text
EIS active search
    -> discovery and deduplication
    -> provisional eligibility and scoring
    -> detail-page open verification
    -> historical analog search
    -> explainable analog similarity/category gating
    -> result/protocol resolution for selected analogs
    -> competition metrics and historical confidence
    -> history-adjusted score
    -> controlled document enrichment
    -> deep technical assessment
    -> final manual-review recommendation
```

The earlier analyzer pipeline remains available independently:

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

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Methodology](docs/METHODOLOGY.md)
- [Outputs](docs/OUTPUTS.md)
- [Radar overview](docs/RADAR.md)
- [Live discovery](docs/RADAR_LIVE_DISCOVERY.md)
- [Document enrichment](docs/RADAR_ENRICHMENT.md)
- [Historical intelligence](docs/RADAR_HISTORICAL_INTELLIGENCE.md)
- [Resilience and recovery](docs/RADAR_RESILIENCE.md)
- [Analog selection](docs/RADAR_ANALOG_SELECTION.md)
- [Historical result extraction](docs/RADAR_RESULT_EXTRACTION.md)
- [Synthetic examples](examples/README.md)
- [Security policy](SECURITY.md)

## Main entry points

- `collect_results.py` — collects EIS search-result cards and writes local datasets.
- `score_results.py` — applies lightweight rule-based scoring and ranking.
- `collect_candidate_details.py` — traverses procurement sections and exposes the importable direct-target collection API used by Radar enrichment.
- `analyze_candidate_documents.py` — extracts and classifies procurement documents and exposes an importable directory-analysis API.
- `python -m radar.runner` — runs the stateful Radar orchestration pipeline.

The document analyzer model remains identified separately from the Radar version.

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

Radar directly uses packages including `PyYAML`, `tzdata`, and `lxml`; these are declared in `requirements.txt`.

Optional local tools improve extraction quality for legacy formats:

- LibreOffice for older Office documents;
- 7-Zip or `unrar` for RAR archives;
- `antiword` for older `.doc` files.

## Configuration

Start from:

```text
config/radar.example.yaml
config/search_profiles.yaml
```

The example configuration covers:

- Moscow timezone handling;
- active discovery mode and query budgets;
- open-procedure verification;
- preliminary scoring thresholds;
- enrichment limits and download budgets;
- historical lookback/search limits;
- analog similarity thresholds;
- customer/supplier-history bounds;
- dumping-risk thresholds;
- cache refresh windows.

Do not put credentials, browser state, downloaded procurement documents, or generated live reports into tracked configuration.

## Safe offline validation

The repository includes synthetic fixtures and regression tests. These checks do not require live EIS collection:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The original analyzer regression mode is also available:

```powershell
.\.venv\Scripts\python.exe .\analyze_candidate_documents.py --run-regression-tests
```

## Controlled Radar examples

Discover currently active procurements using the medium-complexity web profile:

```powershell
.\.venv\Scripts\python.exe -m radar.runner `
  --profile medium_complexity_web `
  --discovery-mode ACTIVE_ONLY `
  --published-within-days 120 `
  --limit 100 `
  --max-pages 2 `
  --max-total-queries 5 `
  --max-total-pages 10 `
  --verify-open-from-detail `
  --output outputs\radar_active `
  --db data\radar_active.db `
  --verbose
```

Plan discovery/enrichment without downloading documents or mutating normal run state:

```powershell
.\.venv\Scripts\python.exe -m radar.runner `
  --profile medium_complexity_web `
  --discovery-mode ACTIVE_ONLY `
  --enrich `
  --enrich-limit 1 `
  --dry-run `
  --output radar_preview `
  --db data\radar_preview.db `
  --verbose
```

Run bounded historical analysis for a completed procurement used only as a retrospective validation source:

```powershell
.\.venv\Scripts\python.exe -m radar.runner `
  --history-only `
  --procurement-number <NUMBER> `
  --allow-completed-source `
  --max-historical-queries 3 `
  --max-historical-pages 2 `
  --max-analogs 10 `
  --output outputs\radar_history `
  --db data\radar_history.db `
  --verbose
```

`--allow-completed-source` is for historical validation; it does not make completed procedures eligible for active participation recommendations.

## Decision layers

Radar preserves distinct stages rather than overwriting earlier judgments:

1. **Preliminary assessment** — card-level eligibility and technical/business fit.
2. **Open verification** — confirms the live status and application deadline from the procurement detail page when configured.
3. **Historical assessment** — evaluates comparable completed procurements and competition evidence.
4. **History-adjusted assessment** — applies an explainable historical adjustment without turning missing history into an automatic rejection.
5. **Deep assessment** — analyzes procurement documents for scope, constraints, economics, integrations, platforms, and evidence completeness.
6. **Final assessment** — combines the available evidence for manual review.

Historical competition is a risk signal, not a predicted winning price.

## Historical competition metrics

Where evidence is available, the historical layer can calculate:

- participant sample size and median/percentiles;
- price-reduction sample size and median/percentiles;
- maximum observed reduction;
- high/extreme/severe reduction rates;
- winner sample size and repeated-winner signal;
- no-application and all-rejected rates;
- customer-history and limited supplier-history context;
- confidence based on sample size, similarity, and result completeness.

Participant and reduction samples are independent: an analog may contribute valid participant evidence even when final price is unavailable, and vice versa.

## Result extraction

The historical result layer distinguishes 44-FZ and 223-FZ navigation paths and can assemble one result from multiple sources. Depending on the procurement, evidence may come from:

- structured result pages;
- protocol main information;
- bid/application lists;
- review/comparison/grade pages;
- final protocol documents;
- contract-result pages where appropriate.

Accepted values retain field-level provenance. Reduction is calculated only from a valid NMCK and a supported final price that does not exceed NMCK.

## Resilience

EIS URLs can be unstable. Radar therefore does not treat a single failed URL as definitive evidence that a procurement does not exist.

The resilience layer supports bounded recovery through:

- supplied URL validation;
- last-known-good URLs;
- exact-number EIS search recovery;
- alternate-section navigation;
- cached source snapshots with explicit freshness;
- bounded retries and explicit temporary/permanent failure states.

Run publication is transactional. A failed or externally blocked attempt does not need to overwrite the last useful `latest.*` output; the newest attempt can be tracked separately via `latest_attempt.json`.

## Supported source formats

The document analyzer currently handles text extraction or structured parsing for:

- `.docx` and `.doc`;
- `.pdf`;
- `.xlsx` and `.xls`;
- `.zip` and `.rar`;
- `.rtf`;
- `.txt`;
- `.html` and `.htm`;
- `.bin` when a supported signature or fallback path is available.

Quality depends on source readability and optional local utilities.

## Repository safety

Generated data must remain local. The repository intentionally excludes live runtime material such as:

- `outputs/`;
- preview run directories;
- SQLite databases and local state;
- downloaded procurement documents;
- Playwright authentication/browser state;
- live EIS HTML and protocol artifacts;
- caches and temporary run directories.

Tracked fixtures are synthetic/test-oriented and must not be replaced with real procurement corpora.

## Known limitations

- The system is deterministic and rule-based; it does not currently use external LLM APIs, embeddings, or ML ranking.
- Historical similarity is explainable but heuristic.
- Historical confidence may remain `LOW` when only a few usable analogs are available.
- Some 44-FZ/223-FZ result layouts may still require parser maintenance.
- Winner evidence is often sparser than participant or price-reduction evidence.
- Some EIS pages may intermittently return unavailable or inconsistent responses.
- Source selectors and navigation logic can require maintenance when EIS changes.
- OCR and legacy-format extraction depend on local tooling.
- The project does not bypass CAPTCHA, authentication boundaries, or closed access.
- The repository is not a production SaaS and does not make automatic participation decisions.

## Development direction

The current milestone closes the first controlled historical-intelligence loop. Future work may build on this foundation with stronger protocol-layout coverage, recurring orchestration, notification channels, review interfaces, and later higher-level market intelligence.

These are roadmap directions, not current features.

## License

MIT License. See [LICENSE](LICENSE).
