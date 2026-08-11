# EIS Procurement Analyzer

EIS Procurement Analyzer is a rule-based Python pipeline for collecting, downloading, classifying, and analyzing public procurement materials from the Russian EIS system.

The repository includes **EIS Procurement Radar**: a stateful decision-support layer that discovers active procurements, verifies whether applications are still open, estimates technical fit, searches historical analogs, extracts competition evidence, detects failed-procurement/republication opportunities, tracks meaningful changes across recurring runs, enriches selected candidates with documents, and produces explainable recommendations for manual review.

The project is **not** a legal, financial, automated participation, or automated bidding service.

## Current status

- Radar version: `0.4.0-r4a-change-feed`
- Historical result extraction version: `0.3.4-r3a-result-extraction`
- Opportunity intelligence version: `0.3.5-r3b-opportunities`
- Full local test suite at the R4A milestone: `151 passed`
- R3A historical intelligence is accepted for controlled recurring use.
- R3B failed-procurement opportunity intelligence is accepted offline and its live failed-history path has been validated against real EIS data.
- R4A adds an idempotent recurring-run change feed on top of existing SQLite state.

The system is intentionally conservative: missing evidence remains missing, partial result data contributes only to supported metrics, and low-confidence signals remain explicitly low-confidence.

## Radar pipeline

```text
EIS active search
    -> discovery and deduplication
    -> preliminary eligibility/scoring
    -> detail-page open verification
    -> historical analog search
    -> result/protocol extraction
    -> competition metrics + confidence
    -> history-adjusted assessment
    -> failed-procurement / republication opportunity intelligence
    -> recurring-state comparison / change feed
    -> controlled document enrichment
    -> deep technical assessment
    -> final manual-review recommendation
```

## What the project demonstrates

- Playwright-based EIS discovery and page traversal;
- active-procedure search with explicit stage/deadline verification;
- separate active and failed-history discovery modes;
- SQLite-backed run, observation, enrichment, historical, opportunity, and transition state;
- resumable new/changed procurement processing;
- idempotent recurring-run change detection;
- explicit `NEW_PROCUREMENT`, deadline/NMCK/status, score/decision, closed-procurement, and opportunity transitions;
- structured change-feed export to JSON, CSV, XLSX, and Markdown;
- controlled document enrichment with budgets and artifact hashing;
- defensive attachment downloads and format validation;
- extraction from DOCX, DOC, PDF, XLSX, XLS, ZIP, RAR, RTF, TXT, HTML, and selected binary sources;
- strict evidence-backed field extraction and conflict handling;
- source recovery and last-known-good caching for unstable EIS URLs;
- explainable historical analog search and category gating;
- source-aware Russian normalization;
- 44-FZ and 223-FZ result/protocol resolution;
- multi-document historical result assembly;
- separate participant, reduction, and winner samples;
- competition metrics, historical confidence, and dumping-risk signals;
- explicit failed-procurement classification;
- explainable republication matching;
- separate opportunity scoring with hard safeguards;
- bounded live failure-history discovery using its own historical lookback window;
- transactional reporting with `latest` vs `latest_attempt` semantics;
- synthetic regression fixtures and automated tests.

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
- [R3B opportunity intelligence](docs/RADAR_OPPORTUNITIES.md)
- [R4A recurring change feed](docs/RADAR_CHANGE_FEED.md)
- [Synthetic examples](examples/README.md)
- [Security policy](SECURITY.md)

## Main entry points

- `collect_results.py` — collects EIS search-result cards and local datasets.
- `score_results.py` — lightweight rule-based scoring and ranking.
- `collect_candidate_details.py` — procurement traversal and importable direct-target collection used by Radar enrichment.
- `analyze_candidate_documents.py` — document extraction/classification and importable directory analysis.
- `python -m radar.runner` — stateful Radar orchestration.

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

Optional local tools can improve extraction of legacy formats: LibreOffice, 7-Zip/`unrar`, and `antiword`.

## Configuration

Start from:

```text
config/radar.example.yaml
config/search_profiles.yaml
```

The example configuration covers discovery budgets, open-status verification, scoring thresholds, enrichment limits, historical search, analog similarity, result collection, dumping-risk thresholds, cache windows, and the R3B `opportunities` section.

## Safe validation

Offline regression tests do not require live EIS access:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The original analyzer regression mode is also available:

```powershell
.\.venv\Scripts\python.exe .\analyze_candidate_documents.py --run-regression-tests
```

## Controlled live discovery

```powershell
.\.venv\Scripts\python.exe -m radar.runner `
  --profile medium_complexity_web `
  --discovery-mode ACTIVE_ONLY `
  --verify-open-from-detail `
  --limit 100 `
  --max-pages 2 `
  --output outputs\radar_active `
  --db data\radar_active.db `
  --verbose
```

Use `python -m radar.runner --help` as the final source of truth for the current CLI surface.

## Historical intelligence

R3A searches completed procurements, selects explainable analogs, resolves result/protocol evidence, and calculates market signals such as participant counts, reductions, repeated-winner evidence, no-application/all-rejected rates, and confidence.

Participant and reduction samples are independent: valid participant evidence may contribute even when final price is unavailable, and valid price evidence may contribute even when participant count is missing.

Historical evidence adjusts but does not overwrite the preliminary assessment. Missing history does not automatically become `REJECT`.

## R3B opportunity intelligence

R3B looks for a different kind of signal: a current procurement may be interesting because a related historical procedure had weak or unsuccessful competition.

The failure model distinguishes `NO_APPLICATIONS`, `SINGLE_APPLICATION`, `ALL_APPLICATIONS_REJECTED`, `NO_ADMITTED_APPLICATIONS`, cancellation, contract-not-concluded, and unknown failure. Zero applications and rejection-based outcomes require explicit evidence.

R3B.1 live validation fixed the failed-history search window and confirmed two real `SINGLE_APPLICATION` events from EIS protocol pages. Live republication matching remains implemented but has not yet been demonstrated with a real bounded pair.

## R4A recurring change feed

R4A compares each persisted run with previous SQLite state and emits only meaningful transitions. Repeated identical runs are idempotent and should produce no change-feed noise.

Current event classes include:

- `NEW_PROCUREMENT`;
- `DEADLINE_CHANGED`;
- `NMCK_CHANGED`;
- `STATUS_CHANGED`;
- preliminary/history score and decision changes;
- `PROCUREMENT_CLOSED`;
- `NEW_OPPORTUNITY`;
- `OPPORTUNITY_UPDATED`;
- `OPPORTUNITY_NO_LONGER_ACTIVE`.

Each change event can preserve the procurement number, event type, detection time, field name, previous/current values, severity, source, and explanation. Reporting exposes the feed in structured runtime outputs including JSON/CSV and the normal XLSX/Markdown reporting surfaces.

The R4A two-run validation used the same local SQLite database: the first fixture run produced 12 `NEW_PROCUREMENT` events; the second identical run produced `0` new, `0` changed, and `0` change events.

## Repository safety

Generated/live data must remain local. The repository intentionally excludes runtime outputs, SQLite databases, downloaded procurement documents, browser authentication state, live EIS HTML/protocol artifacts, caches, and temporary run directories.

Tracked fixtures are synthetic/test-oriented and should not be replaced with real procurement corpora.

## Known limitations

- The system is deterministic and rule-based; it does not currently use external LLM APIs, embeddings, or ML ranking.
- Historical similarity and republication scoring are heuristic and explainable, not probabilistic.
- Historical confidence may remain low with small usable samples.
- Some 44-FZ/223-FZ result layouts may still require parser maintenance.
- Winner evidence is often sparser than participant or reduction evidence.
- EIS pages may intermittently return unavailable or inconsistent responses.
- Live republication matching has not yet been demonstrated with a real bounded pair.
- R4A detects changes but does not yet schedule recurring runs or send notifications.
- The project does not bypass CAPTCHA, authentication boundaries, or closed access.
- Final participation decisions require human legal, commercial, and technical review.

## Development direction

R4A provides the state-diff layer needed for operational monitoring. The next useful step is recurring orchestration: reliable scheduled/looped execution with locking, run lifecycle control, retention, and failure isolation before notification channels are added.

## License

MIT License. See [LICENSE](LICENSE).
