# EIS Procurement Analyzer

EIS Procurement Analyzer is a rule-based Python pipeline for collecting, downloading, classifying, and analyzing public procurement materials from the Russian EIS system.

The repository includes **EIS Procurement Radar**: a stateful decision-support layer that discovers active procurements, verifies open status, evaluates technical fit, searches historical analogs, extracts competition evidence, detects failed-procurement/republication opportunities, tracks changes across recurring runs, filters those changes into a compact alert feed, optionally delivers alerts to Telegram, and exposes a stable Windows production launcher with preflight validation.

The project is **not** a legal, financial, automated participation, or automated bidding service.

## Current status

- Radar version: `0.4.6-r4f1-state-guardrails`
- Historical result extraction version: `0.3.4-r3a-result-extraction`
- Opportunity intelligence version: `0.3.5-r3b-opportunities`
- Full local test suite at the R4F.1 milestone: `183 passed`
- R4A adds an idempotent recurring-run change feed.
- R4B adds reliable recurring execution with locking, lifecycle persistence, failure isolation, and retention.
- R4C adds deterministic alert filtering, prioritization, deduplication, and alert-history idempotency.
- R4D adds optional Telegram delivery with persisted alert/chunk status and retry-safe partial delivery.
- R4E adds a production profile, stable path resolution, fail-fast preflight checks, and a scheduler-friendly entry point.
- R4F adds a Windows launcher contract for Task Scheduler, timestamped runtime logs, exact exit-code propagation, and narrow runtime-artifact ignores.
- R4F.1 hardens state transitions so absence from a bounded run is never treated as evidence of procurement closure or opportunity inactivity.

## Production entry points

Direct Python preflight:

```powershell
.\.venv\Scripts\python.exe -m radar.runner --production --preflight-only --verbose
```

Direct Python production run:

```powershell
.\.venv\Scripts\python.exe -m radar.runner --production
```

Windows launcher:

```powershell
scripts\radar-production.cmd --preflight-only
scripts\radar-production.cmd
```

The launcher resolves the project root from its own location, explicitly uses `.venv\Scripts\python.exe`, writes stdout/stderr to `runtime-logs\radar-YYYYMMDD-HHMMSS.log`, and returns the exact Radar exit code.

## State-transition guardrails

Recurring runs are intentionally bounded. A procurement may disappear from one run simply because the search scope, page budget, query mix, or EIS result ordering changed. R4F.1 therefore treats **absence as absence, not as closure**.

`PROCUREMENT_CLOSED` is emitted only when the procurement is explicitly observed with a supported closed status such as completed, cancelled, closed, or contract signed. Likewise, `OPPORTUNITY_NO_LONGER_ACTIVE` must come from an explicit opportunity transition; it is not inferred from a missing bounded-run observation.

This prevents absence-only state changes from being promoted into alerts or sent through Telegram.

## Windows Task Scheduler contract

The scheduled task should use the **absolute local path** to `scripts\radar-production.cmd` as `Program/script`. That absolute path is deployment-specific and is intentionally not committed to the repository.

Recommended shape:

```text
Program/script: <absolute local path>\scripts\radar-production.cmd
Arguments:      (empty for a normal production run)
Start in:       optional
```

For deployment validation, use:

```text
Arguments: --preflight-only
```

The launcher does not depend on the Task Scheduler working directory.

## Configuration and secrets

Production defaults live in `config/radar.production.yaml`. Runtime DB/output paths are resolved against the project root rather than the caller's current working directory.

Telegram credentials remain environment-based:

```text
RADAR_TELEGRAM_BOT_TOKEN
RADAR_TELEGRAM_CHAT_ID
```

Do not place real secrets in tracked config, Task Scheduler command-line arguments, or repository files.

## Runtime data and repository safety

Generated/live data must remain local. The repository excludes runtime outputs, SQLite databases, downloaded procurement documents, browser state, live EIS HTML/protocol artifacts, caches, locks, credentials, `runtime-logs/`, and the root-level runtime validation artifact `RADAR_R3A1_LIVE_VALIDATION.md`.

Tracked fixtures are synthetic/test-oriented and should not be replaced with real procurement corpora.

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
- [R4F Windows deployment](docs/RADAR_WINDOWS_DEPLOYMENT.md)
- [R4F.1 state-transition guardrails](docs/RADAR_STATE_GUARDRAILS.md)
- [Synthetic examples](examples/README.md)
- [Security policy](SECURITY.md)

## Safe validation

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

R4F.1 validation covers absence-only procurement state, absence-only opportunity state, explicit closure, explicit opportunity inactivity, downstream alert suppression, and proof that absence-only cases do not trigger Telegram delivery.

## Known limitations

- The system is deterministic and rule-based; it does not currently use external LLM APIs, embeddings, or ML ranking.
- Historical similarity and republication scoring are heuristic and explainable, not probabilistic.
- Historical confidence may remain low with small usable samples.
- Some EIS layouts may still require parser maintenance.
- Live republication matching has not yet been demonstrated with a real bounded pair.
- The repository provides deployment support but does not automatically register a Windows Task Scheduler task.
- Telegram support is outbound-only: no bot commands, polling, or inbound workflow is implemented.
- The project does not bypass CAPTCHA, authentication boundaries, or closed access.
- Final participation decisions require human legal, commercial, and technical review.

## Development direction

R4A-R4F.1 now provide the operational chain from recurring procurement monitoring through alert delivery, Windows scheduler-safe execution, and evidence-based state transitions. The next step is machine deployment: configure local Telegram environment variables, rerun production preflight with delivery enabled, perform a controlled production run, and only then register the Windows Task Scheduler job.

## License

MIT License. See [LICENSE](LICENSE).
