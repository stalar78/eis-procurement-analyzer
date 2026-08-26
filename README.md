# EIS Procurement Analyzer

EIS Procurement Analyzer is a rule-based Python pipeline for collecting, downloading, classifying, and analyzing public procurement materials from the Russian EIS system.

The repository includes **EIS Procurement Radar**: a stateful decision-support layer that discovers active procurements, verifies open status, evaluates technical fit, searches historical analogs, extracts competition evidence, detects failed-procurement/republication opportunities, tracks changes across recurring runs, filters those changes into a compact alert feed, optionally delivers alerts to Telegram, and supports recurring Windows production execution through a passwordless current-user Startup background runner.

The project is **not** a legal, financial, automated participation, or automated bidding service.

## Current status

- Radar version label: `0.6.0-r4h-source-resilience`
- Historical result extraction version: `0.3.4-r3a-result-extraction`
- Opportunity intelligence version: `0.3.5-r3b-opportunities`
- Latest accepted local suite after R4H source-resilience hardening: `297 passed`
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
- R4G.4 adds GitHub Actions coverage for both Linux and Windows, including the Windows launcher/background-loop production surface and a full Windows pytest run.
- R4G.5 pins all direct runtime dependencies and the dev/test dependency to exact validated versions for reproducible fresh installs.
- R4G.6 adds a read-only runtime health command that reports the latest recurring lifecycle state, last successful run age, and a deterministic `HEALTHY` / `STALE` / `UNHEALTHY` classification.
- R4G.6.1 hardens health semantics with separate `STARTED` run-duration checks, finite positive threshold validation, and fail-closed handling for unknown lifecycle states.
- R4G.6.2 adds runtime build provenance: `--version` prints the application version and short Git build identity, while generated report summaries persist both `radar_version` and `build_identity`.
- R4H.1 adds structured detail-unavailable failure diagnostics so transport, identity, status, deadline, and source-resolution failures are distinguishable without exposing raw exception text.
- R4H.2 uses native Windows certificate trust for production EIS requests while preserving ordinary Requests verification on non-Windows platforms; insecure TLS bypasses remain prohibited.
- R4H.3 recovers stale or invalid detail sources through bounded source resolution while preserving 44-FZ / 223-FZ source-family safety.
- R4H.4 hardens exact-search semantics so a recognized exact-number search page with no matching result can be distinguished from an unrecognized or temporarily unavailable search response.
- R4H.5 persists live-validated last-known-good detail URLs across runs and reuses them only through fresh live retrieval and identity/detail verification.
- R4H.6 adds one bounded retry for a previously proven canonical source when the same source transiently fails, without adding retries for unproven direct URLs.
- R4H.6.1 preserves proven-canonical retry diagnostics through later recovery or final failure so production evidence shows the complete fallback chain.
- R4H.7 degrades same-run `NOT_FOUND_CONFIRMED` to `PROVEN_SOURCE_TEMPORARILY_UNAVAILABLE` when recent live proof exists, while keeping the candidate only as `DETAIL_UNAVAILABLE` rather than falsely upgrading it to `VERIFIED_OPEN`.
- Telegram end-to-end delivery has been validated through a controlled live run from EIS discovery through alert delivery.
- Windows Startup deployment has been validated by an actual reboot/login: Windows started the hidden background loop automatically, the loop recovered the previous-session lock, executed Radar successfully, and remained alive for the next three-hour cycle.
- R4H was production-validated on live EIS runs: previously proven canonical URLs could return repeated HTTP 404 responses while later resolver attempts sometimes recovered the same procurement live; the final model therefore records recent-proof temporary unavailability instead of treating one unstable run as durable source disappearance.

## Production entry points

Direct Python preflight:

```powershell
.\.venv\Scripts\python.exe -m radar.runner --production --preflight-only --verbose
```

Direct Python production run:

```powershell
.\.venv\Scripts\python.exe -m radar.runner --production
```

Read-only production health check:

```powershell
.\.venv\Scripts\python.exe -m radar.runner --production --health
```

The default last-success freshness threshold is seven hours and the default maximum duration for a current `STARTED` run is twelve hours. `HEALTHY` exits `0`, `STALE` exits `2`, and `UNHEALTHY` exits `3`. Invalid health thresholds, unknown lifecycle states, failed/locked latest runs, and overlong or malformed `STARTED` runs fail closed as `UNHEALTHY`.

Runtime provenance:

```powershell
.\.venv\Scripts\python.exe -m radar.runner --version
```

The version command reports the Radar application version and a cached short Git `HEAD` identity when available. If Git metadata is unavailable, build identity degrades safely to `unknown` without failing the Radar pipeline.

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

R4H extends the unavailable-evidence contract across recurring live runs. A source URL is remembered only after successful live validation; later reuse is always a fresh HTTP fetch and must pass the same procurement-identity and detail checks. If a recently proven source and bounded recovery both fail in an unstable EIS cycle, Radar returns `DETAIL_UNAVAILABLE` with `PROVEN_SOURCE_TEMPORARILY_UNAVAILABLE` and `DEGRADED_BY_RECENT_PROOF`. Historical proof therefore weakens an absence claim but never substitutes for live evidence of `VERIFIED_OPEN`.

## TLS source integrity

Production EIS HTTP retrieval uses normal certificate verification. On Windows, Radar integrates native system trust for Requests so EIS certificate-chain differences do not require an insecure bypass. Production paths must not use `verify=False`, `CERT_NONE`, or suppressed certificate warnings.

TLS failures degrade to existing unavailable semantics rather than becoming evidence. There is no insecure fallback to disabled certificate verification.

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

The latest accepted local suite after R4H source-resilience hardening is `297 passed`.

## Known limitations

- The system is deterministic and rule-based; it does not currently use external LLM APIs, embeddings, or ML ranking.
- Historical similarity and republication scoring are heuristic and explainable, not probabilistic.
- Historical confidence may remain low with small usable samples.
- Some EIS layouts may still require parser maintenance; malformed/partial search cards can be skipped with a warning.
- Live republication matching has not yet been demonstrated with a real bounded pair.
- The current Windows deployment is user-session based: Radar runs while the Windows user is logged in; it is not a Windows service or unattended server deployment.
- GitHub Actions exercises Linux and Windows test surfaces, including Windows launcher/background-loop behavior in an isolated runner environment; the real Startup installation itself is validated separately on the workstation rather than modified by CI.
- Direct dependencies are pinned to exact versions, but there is no transitive lockfile yet.
- Runtime health remains a local read-only CLI check; it is not yet pushed to an independent watchdog or notification channel.
- Branch protection/required status checks are not yet enforced on `main`; CI is therefore a detective control rather than a mandatory merge gate.
- Telegram support is outbound-only: no bot commands, polling, or inbound workflow is implemented.
- The project does not bypass CAPTCHA, authentication boundaries, or closed access.
- Final participation decisions require human legal, commercial, and technical review.

## Development direction

The operational chain is validated from Windows login through Startup background execution, production preflight, recurring Radar execution, evidence-based state transitions, alert filtering, Telegram delivery, resilient lock recovery, cross-platform CI coverage, reproducible direct dependency installation, hardened read-only runtime health evaluation, build provenance, native Windows TLS trust, bounded detail-source recovery, cross-run last-known-good persistence, proven-canonical retry observability, and conservative recent-proof absence semantics. The source-resilience line R4H is production-validated; future parser/resilience work should be driven by new live evidence rather than additional speculative retries. Independent watchdog signaling, branch protection, and transitive locking remain explicit follow-up controls.

## License

MIT License. See [LICENSE](LICENSE).
