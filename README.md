# EIS Procurement Analyzer

EIS Procurement Analyzer is a rule-based Python pipeline for collecting, downloading, classifying, and analyzing public procurement materials from the Russian EIS system.

The repository includes **EIS Procurement Radar**: a stateful decision-support layer that discovers active procurements, verifies open status, evaluates technical fit, searches historical analogs, extracts competition evidence, detects failed-procurement/republication opportunities, tracks changes across recurring runs, filters those changes into a compact alert feed, optionally delivers alerts to Telegram, and now exposes a stable production-style recurring entry point with preflight validation.

The project is **not** a legal, financial, automated participation, or automated bidding service.

## Current status

- Radar version: `0.4.4-r4e-production-profile`
- Historical result extraction version: `0.3.4-r3a-result-extraction`
- Opportunity intelligence version: `0.3.5-r3b-opportunities`
- Full local test suite at the R4E milestone: `176 passed`
- R4A adds an idempotent recurring-run change feed.
- R4B adds reliable recurring execution with locking, lifecycle persistence, failure isolation, and retention.
- R4C adds deterministic alert filtering, prioritization, deduplication, and alert-history idempotency.
- R4D adds optional Telegram delivery with persisted alert/chunk status and retry-safe partial delivery.
- R4E adds a production profile, stable path resolution, fail-fast preflight checks, and a scheduler-friendly entry point.

The system is intentionally conservative: missing evidence remains missing, partial result data contributes only to supported metrics, low-confidence signals remain explicit, and delivery/operational layers do not make business decisions.

## Radar pipeline

```text
production/preflight entry point
    -> recurring run orchestration / lock
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
    -> alert filtering / deduplication / priority
    -> optional Telegram delivery
    -> controlled document enrichment
    -> deep technical assessment
    -> transactional publication
    -> lifecycle record + retention
```

## What the project demonstrates

- Playwright-based EIS discovery and page traversal;
- active-procedure search with explicit stage/deadline verification;
- SQLite-backed run, historical, opportunity, change, lifecycle, alert, and delivery state;
- idempotent recurring change detection and alert generation;
- deterministic notification-ready filtering;
- optional Telegram Bot API delivery over HTTPS;
- persisted alert-level and chunk-level delivery state;
- retryable partial delivery without resending successful chunks;
- recurring-run locking with stale-lock recovery;
- failure isolation and bounded runtime retention;
- production-style `--production` mode;
- scheduler-safe `--preflight-only` validation;
- stable production config/path resolution independent of process working directory;
- project-relative runtime DB/output paths without machine-specific absolute paths;
- environment-based Telegram credentials with delivery disabled by default;
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
- [R4C alert filtering](docs/RADAR_ALERTS.md)
- [R4D Telegram delivery](docs/RADAR_TELEGRAM.md)
- [R4E production profile](docs/RADAR_PRODUCTION.md)
- [Synthetic examples](examples/README.md)
- [Security policy](SECURITY.md)

## Main entry point

```powershell
.\.venv\Scripts\python.exe -m radar.runner --help
```

### Production preflight

```powershell
.\.venv\Scripts\python.exe -m radar.runner --production --preflight-only --verbose
```

Production mode loads `config/radar.production.yaml`, normalizes relative runtime paths against the project root, validates the runtime environment, and returns exit code `78` on preflight failure without starting the Radar pipeline.

### Production recurring run

```powershell
.\.venv\Scripts\python.exe -m radar.runner --production
```

`--production` automatically routes through the existing recurring orchestration and lock behavior. It is intended to be called by an external scheduler; the application does not contain an internal cron loop.

## Configuration and secrets

Production defaults live in:

```text
config/radar.production.yaml
```

The tracked production profile uses project-relative runtime paths such as `outputs/radar` and `data/radar.db`. Production path resolution does not depend on the caller's current working directory.

Telegram delivery remains disabled by default. Preferred credential sources are environment variables:

```text
RADAR_TELEGRAM_BOT_TOKEN
RADAR_TELEGRAM_CHAT_ID
```

Do not commit real tokens, chat IDs, local databases, generated outputs, or downloaded procurement data.

## Safe validation

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

R4E validation covers successful production preflight, missing Telegram environment values when Telegram is enabled, invalid/unwritable runtime paths, invalid operational values, recurring-mode routing, secret-safe errors, fail-fast preflight, and execution from an unrelated current working directory.

## Repository safety

Generated/live data must remain local. The repository intentionally excludes runtime outputs, SQLite databases, downloaded procurement documents, browser state, live EIS HTML/protocol artifacts, caches, locks, and credentials.

Tracked fixtures are synthetic/test-oriented and should not be replaced with real procurement corpora.

## Known limitations

- The system is deterministic and rule-based; it does not currently use external LLM APIs, embeddings, or ML ranking.
- Historical similarity and republication scoring are heuristic and explainable, not probabilistic.
- Historical confidence may remain low with small usable samples.
- Some EIS layouts may still require parser maintenance.
- Live republication matching has not yet been demonstrated with a real bounded pair.
- Windows Task Scheduler registration is not yet automated by the project.
- Telegram support is outbound-only: no bot commands, polling, or inbound workflow is implemented.
- The project does not bypass CAPTCHA, authentication boundaries, or closed access.
- Final participation decisions require human legal, commercial, and technical review.

## Development direction

R4A-R4E provide the operational chain from recurring procurement monitoring through alert delivery and a stable production entry point. The next step is deployment handoff: define the concrete Windows Task Scheduler task, environment setup, schedule, working parameters, and controlled first scheduled run without adding new business logic.

## License

MIT License. See [LICENSE](LICENSE).
