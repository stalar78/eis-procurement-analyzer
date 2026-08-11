# EIS Procurement Analyzer

EIS Procurement Analyzer is a rule-based Python pipeline for collecting, downloading, classifying, and analyzing public procurement materials from the Russian EIS system.

The repository includes **EIS Procurement Radar**: a stateful decision-support layer that discovers active procurements, verifies whether applications are still open, estimates technical fit, searches historical analogs, extracts competition evidence, detects failed-procurement/republication opportunities, tracks meaningful changes across recurring runs, and can now execute those recurring runs with locking, lifecycle tracking, failure isolation, and bounded retention.

The project is **not** a legal, financial, automated participation, or automated bidding service.

## Current status

- Radar version: `0.4.1-r4b-orchestration`
- Historical result extraction version: `0.3.4-r3a-result-extraction`
- Opportunity intelligence version: `0.3.5-r3b-opportunities`
- Full local test suite at the R4B milestone: `156 passed`
- R3A historical intelligence is accepted for controlled recurring use.
- R3B failed-procurement opportunity intelligence is accepted offline and its live failed-history path has been validated against real EIS data.
- R4A adds an idempotent recurring-run change feed.
- R4B adds reliable unattended recurring execution primitives without embedding a scheduler.

The system is intentionally conservative: missing evidence remains missing, partial result data contributes only to supported metrics, and low-confidence signals remain explicitly low-confidence.

## Radar pipeline

```text
recurring run orchestration / lock
    -> EIS active search
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
    -> transactional publication
    -> lifecycle record + retention
```

## What the project demonstrates

- Playwright-based EIS discovery and page traversal;
- active-procedure search with explicit stage/deadline verification;
- separate active and failed-history discovery modes;
- SQLite-backed run, observation, enrichment, historical, opportunity, transition, and recurring-lifecycle state;
- resumable new/changed procurement processing;
- idempotent recurring-run change detection;
- explicit procurement/opportunity transition events;
- structured change-feed export to JSON, CSV, XLSX, and Markdown;
- recurring-run lock with stale-lock recovery;
- lifecycle statuses `STARTED`, `SUCCESS`, `FAILED`, and `SKIPPED_LOCKED`;
- failure isolation so an unsuccessful recurring run does not replace the last successful published result;
- bounded retention for archived successful and failed run directories;
- controlled document enrichment with budgets and artifact hashing;
- defensive attachment downloads and format validation;
- extraction from DOCX, DOC, PDF, XLSX, XLS, ZIP, RAR, RTF, TXT, HTML, and selected binary sources;
- strict evidence-backed field extraction and conflict handling;
- source recovery and last-known-good caching for unstable EIS URLs;
- explainable historical analog search and category gating;
- 44-FZ and 223-FZ result/protocol resolution;
- explicit failed-procurement classification and opportunity scoring;
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
- [R4B recurring orchestration](docs/RADAR_ORCHESTRATION.md)
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

The example configuration covers discovery budgets, open-status verification, scoring thresholds, enrichment limits, historical search, opportunity intelligence, and recurring-run controls.

R4B recurring configuration includes stale-lock timeout and retention counts for successful/failed run directories.

## Safe validation

Offline regression tests do not require live EIS access:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
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

For unattended external scheduling, the same pipeline can be invoked with `--recurring`. The program itself does not run an internal cron loop; an external scheduler can call it at the desired interval.

Use `python -m radar.runner --help` as the final source of truth for the current CLI surface.

## R4A recurring change feed

R4A compares each persisted run with previous SQLite state and emits only meaningful transitions. Repeated identical runs are idempotent and should produce no change-feed noise.

Events include new procurements, deadline/NMCK/status changes, score/decision changes, procurement closure, and opportunity activation/update/deactivation.

## R4B recurring orchestration

R4B makes repeated execution safe enough for an external scheduler:

- `radar.lock` prevents overlapping recurring runs;
- stale locks can be recovered after a configurable timeout;
- lifecycle is appended to SQLite as `STARTED`, `SUCCESS`, `FAILED`, or `SKIPPED_LOCKED`;
- locked/skipped runs use exit code `75`, ordinary failure uses `1`, success uses `0`;
- a failed run does not replace the last successful published output;
- the lock is released through the failure path;
- successful and failed archived run directories can be retained with bounded counts.

The R4B validation confirmed two sequential successful runs on one SQLite DB, with the second run producing `new=0`, `changed=0`, and no change-feed events. Locking, stale-lock recovery, failure isolation, and retention are covered by deterministic tests.

## Repository safety

Generated/live data must remain local. The repository intentionally excludes runtime outputs, SQLite databases, downloaded procurement documents, browser authentication state, live EIS HTML/protocol artifacts, caches, and temporary run directories.

Tracked fixtures are synthetic/test-oriented and should not be replaced with real procurement corpora.

## Known limitations

- The system is deterministic and rule-based; it does not currently use external LLM APIs, embeddings, or ML ranking.
- Historical similarity and republication scoring are heuristic and explainable, not probabilistic.
- Historical confidence may remain low with small usable samples.
- Some 44-FZ/223-FZ result layouts may still require parser maintenance.
- EIS pages may intermittently return unavailable or inconsistent responses.
- Live republication matching has not yet been demonstrated with a real bounded pair.
- R4B provides recurring execution safety but does not install or manage Windows Task Scheduler jobs and does not contain an internal scheduler loop.
- No notification channel is implemented yet.
- The project does not bypass CAPTCHA, authentication boundaries, or closed access.
- Final participation decisions require human legal, commercial, and technical review.

## Development direction

R4A and R4B provide the operational base for daily monitoring. The next useful layer is notification-ready filtering: convert the full change feed into a small set of high-value alert events before adding Telegram, email, or another delivery channel.

## License

MIT License. See [LICENSE](LICENSE).
