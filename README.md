# EIS Procurement Analyzer

EIS Procurement Analyzer is a rule-based Python pipeline for collecting, downloading, classifying, and analyzing public procurement materials from the Russian EIS system.

The repository includes **EIS Procurement Radar**: a stateful decision-support layer that discovers active procurements, verifies open status, evaluates technical fit, searches historical analogs, extracts competition evidence, detects failed-procurement/republication opportunities, tracks changes across recurring runs, filters those changes into a compact alert feed, optionally delivers alerts to Telegram, and supports recurring Windows production execution through a passwordless current-user Startup background runner.

The project is **not** a legal, financial, automated participation, or automated bidding service.

## Current status

- Radar version label: `0.4.8-r4f3-detail-verification-degradation`
- Historical result extraction version: `0.3.4-r3a-result-extraction`
- Opportunity intelligence version: `0.3.5-r3b-opportunities`
- Latest accepted local suite after R4G hardening: `226 passed`
- R4A adds an idempotent recurring-run change feed.
- R4B adds reliable recurring execution with locking, lifecycle persistence, failure isolation, and retention.
- R4C adds deterministic alert filtering, prioritization, deduplication, and alert-history idempotency.
- R4D adds optional Telegram delivery with persisted alert/chunk status and retry-safe partial delivery.
- R4E adds a production profile, stable path resolution, fail-fast preflight checks, and a scheduler-friendly entry point.
- R4F adds a Windows launcher contract, timestamped runtime logs, exact exit-code propagation, and narrow runtime-artifact ignores.
- R4F.1 hardens state transitions so absence from a bounded run is never treated as evidence of procurement closure or opportunity inactivity.
- R4F.2 adds Windows PID-aware orphan-lock recovery while preserving conservative age-based fallback behavior.
- R4F.2.1 isolates Telegram-related tests from host environment credentials without changing production credential precedence.
- R4F.3 keeps provisionally-open candidates when detail verification is temporarily unavailable, while explicit closed/cancelled/conflict evidence remains rejecting.
- R4G hardening repairs the detail-evidence contract, restores normal TLS certificate verification in production EIS HTTP paths, removes the deprecated Task Scheduler deployment path, and hardens the passwordless Startup background loop with atomic singleton ownership and orphan/PID-reuse recovery.
- Telegram end-to-end delivery has been validated through a controlled live run from EIS discovery through alert delivery.
- Windows Startup deployment has been validated by an actual reboot/login: Windows started the hidden background loop automatically, the loop recovered the previous-session lock, executed Radar successfully, and remained alive for the next three-hour cycle.

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
scripts\radar-production.cmd --send-telegram-alerts
```

The launcher resolves the project root from its own location, explicitly uses `.venv\Scripts\python.exe`, writes stdout/stderr to `runtime-logs\radar-YYYYMMDD-HHMMSS.log`, and returns the exact Radar exit code.

## State-transition guardrails

Recurring runs are intentionally bounded. A procurement may disappear from one run simply because the search scope, page budget, query mix, or EIS result ordering changed. R4F.1 therefore treats **absence as absence, not as closure**.

`PROCUREMENT_CLOSED` is emitted only when the procurement is explicitly observed with a supported closed status such as completed, cancelled, closed, or contract signed. Likewise, `OPPORTUNITY_NO_LONGER_ACTIVE` must come from an explicit opportunity transition; it is not inferred from a missing bounded-run observation.

This prevents absence-only state changes from being promoted into alerts or sent through Telegram.

## Detail-verification evidence contract

`ACTIVE_ONLY` discovery first identifies provisionally-open cards from search evidence. Detail-page verification strengthens that evidence when available, but temporary detail-page failure is not treated as proof that a procurement is closed.

The current verification contract is:

- `VERIFIED_OPEN` requires the expected procurement identity, an explicit active/open detail status, and an explicit future detail deadline;
- card status/deadline may be used for comparison and conflict detection, but never as fallback evidence for missing detail fields;
- `DETAIL_UNAVAILABLE` keeps the provisionally-open candidate and preserves diagnostics;
- verification skipped because of the configured limit keeps the provisionally-open candidate;
- `VERIFIED_CLOSED` / `VERIFIED_CANCELLED` reject the candidate;
- `STATUS_CONFLICT` / `DEADLINE_CONFLICT` retain conservative rejecting semantics.

This prevents an HTTP 200 page with missing/irrelevant content from becoming `VERIFIED_OPEN` by reusing the original card evidence.

## TLS source integrity

Production EIS HTTP retrieval uses normal `requests` certificate verification. Production paths must not use `verify=False` or suppress `InsecureRequestWarning`.

TLS failures degrade to existing unavailable semantics rather than becoming evidence: detail verification becomes `DETAIL_UNAVAILABLE`, while source resolution remains temporarily unavailable. There is no insecure fallback to disabled certificate verification.

## Windows Startup deployment

The current workstation deployment uses:

```text
scripts\radar-production.cmd
scripts\radar-background-loop.ps1
scripts\install-radar-startup.ps1
```

`install-radar-startup.ps1` creates or updates one shortcut in the current user's Windows Startup folder. The shortcut launches a hidden PowerShell process without administrator rights or a Windows password. The background loop invokes:

```text
scripts\radar-production.cmd --send-telegram-alerts
```

and repeats every three hours.

The background loop uses an atomic lock with PID, process start time, and a unique owner token. Dead, malformed, legacy, or PID-reused locks are recoverable; a live matching owner blocks a second runner with exit code `75`; cleanup removes only a lock still owned by the current process.

Install or refresh the Startup entry:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-radar-startup.ps1
```

The previous `Stalar Procurement Radar` Task Scheduler task is deprecated and should remain disabled/removed. The tracked Task Scheduler registration helper has been removed.

## Configuration and secrets

Production defaults live in `config/radar.production.yaml`. Runtime DB/output paths are resolved against the project root rather than the caller's current working directory.

Telegram credentials remain environment-based:

```text
RADAR_TELEGRAM_BOT_TOKEN
RADAR_TELEGRAM_CHAT_ID
```

Do not place real secrets in tracked config, Startup shortcut arguments, repository files, or documentation.

The tracked production profile keeps Telegram disabled by default. The deployed background loop enables delivery at runtime with `--send-telegram-alerts` while credentials remain in the Windows user environment.

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
- [Windows deployment](docs/RADAR_WINDOWS_DEPLOYMENT.md)
- [R4F.1 state-transition guardrails](docs/RADAR_STATE_GUARDRAILS.md)
- [Synthetic examples](examples/README.md)
- [Security policy](SECURITY.md)

## Safe validation

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The latest accepted local suite after evidence-contract, TLS, and background-runner hardening is `226 passed`.

## Known limitations

- The system is deterministic and rule-based; it does not currently use external LLM APIs, embeddings, or ML ranking.
- Historical similarity and republication scoring are heuristic and explainable, not probabilistic.
- Historical confidence may remain low with small usable samples.
- Some EIS layouts may still require parser maintenance; malformed/partial search cards can be skipped with a warning.
- Live republication matching has not yet been demonstrated with a real bounded pair.
- The current Windows deployment is user-session based: Radar runs while the Windows user is logged in; it is not a Windows service or unattended server deployment.
- Remote CI does not yet exercise the Windows-specific launcher/Startup contract; Windows CI remains a planned hardening step.
- Dependency versions are not yet fully locked for reproducible production environments.
- Telegram support is outbound-only: no bot commands, polling, or inbound workflow is implemented.
- The project does not bypass CAPTCHA, authentication boundaries, or closed access.
- Final participation decisions require human legal, commercial, and technical review.

## Development direction

The current operational chain is validated from Windows login through Startup background execution, production preflight, recurring Radar execution, evidence-based state transitions, alert filtering, Telegram delivery, and resilient lock recovery. The next hardening priorities are Windows CI for the production-specific surface and reproducible dependency locking, followed by parser/resilience improvements driven by real recurring runs.

## License

MIT License. See [LICENSE](LICENSE).
