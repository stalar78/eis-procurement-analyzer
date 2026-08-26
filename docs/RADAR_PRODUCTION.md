# R4E Production Profile

## Purpose

R4E adds a stable production-style entry point for recurring EIS Procurement Radar runs. The goal is to make the runtime predictable for an external Windows launcher/background runner without embedding scheduling policy inside the Python application.

Current R4E milestone label: `0.4.4-r4e-production-profile`.

Current Radar application version: `0.6.0-r4h-source-resilience`.

The active workstation deployment now uses the current-user Windows Startup folder plus `scripts/radar-background-loop.ps1`; the earlier Task Scheduler path is deprecated and removed from the tracked deployment surface.

## Production entry point

The normal production command is:

```powershell
.\.venv\Scripts\python.exe -m radar.runner --production
```

`--production` automatically routes through the existing recurring orchestration introduced in R4B. Locking, stale-lock recovery, lifecycle persistence, failure isolation, and retention therefore remain the same as in ordinary recurring mode.

## Production configuration

The default tracked production profile is:

```text
config/radar.production.yaml
```

When `--production` is used without an explicit `--config`, the runner resolves this file from the project root rather than from the process current working directory.

The tracked profile intentionally uses relative runtime paths:

```text
outputs/radar
data/radar.db
```

In production/preflight mode these paths are normalized against the project root. This prevents any external Windows launcher started from an unrelated directory from accidentally creating Radar state relative to that directory.

No machine-specific absolute paths should be committed to the production profile.

## Preflight

Use:

```powershell
.\.venv\Scripts\python.exe -m radar.runner --production --preflight-only --verbose
```

Preflight validates the runtime environment and exits before discovery or recurring lifecycle execution.

Checks currently cover:

- readable production config;
- writable or safely creatable SQLite parent directory;
- writable or safely creatable output directory;
- positive stale-lock timeout;
- non-negative successful/failed retention counts;
- valid Telegram timeout, retry, backoff, and message-size values;
- Telegram credentials when Telegram delivery is enabled.

A preflight failure returns exit code `78`.

## Runtime health

R4G.6 adds a lightweight read-only operational health check on top of the existing `recurring_run_lifecycle` state. It does not create a second health database and does not run EIS discovery, Telegram delivery, or a recurring cycle.

Use the production profile with:

```powershell
.\.venv\Scripts\python.exe -m radar.runner --production --health
```

The default last-success freshness threshold is `7.0` hours. R4G.6.1 adds a separate maximum duration for the current `STARTED` run, default `12.0` hours.

Both thresholds can be overridden for diagnostics:

```powershell
.\.venv\Scripts\python.exe -m radar.runner --production --health --health-max-age-hours 10 --health-max-run-hours 12
```

Both values must be finite and greater than zero. Zero, negative values, NaN, and infinities are rejected and return the health `UNHEALTHY` exit code.

The command reports the latest lifecycle status, the last successful recurring run timestamp, its age, and one of three classifications:

- `HEALTHY` — a successful recurring run exists and is within the freshness threshold, and any current `STARTED` run is still within its maximum run duration; exit code `0`;
- `STALE` — a successful recurring run exists but is older than the freshness threshold while no stronger unhealthy condition is present; exit code `2`;
- `UNHEALTHY` — no successful recurring run exists, lifecycle data is unavailable/invalid, the latest lifecycle state is `FAILED` / `SKIPPED_LOCKED`, an unknown state is observed, or a current `STARTED` run is malformed or exceeds the maximum run duration; exit code `3`.

A current failure is intentionally not hidden by an earlier fresh success. Likewise, a `STARTED` row that has exceeded the maximum execution duration is `UNHEALTHY` even when a recent successful run exists.

The health database is opened read-only. The command remains an operator-facing local check, not an independent watchdog or notification service.

## Runtime provenance

R4G.6.2 adds a simple runtime build identity without introducing a packaging/release subsystem.

Use:

```powershell
.\.venv\Scripts\python.exe -m radar.runner --version
```

The command prints:

- the Radar application version;
- a cached short Git `HEAD` build identity when the checkout metadata is available.

If Git is unavailable, times out, or no SHA can be resolved, build identity is reported as `unknown`. This condition never blocks ordinary Radar execution.

Generated report summaries preserve the existing `radar_version` field and also include `build_identity`, so stored output can be associated with a concrete code revision when Git metadata is available.

The current R4H application label is `0.6.0-r4h-source-resilience`. R4H changes source/detail resilience while preserving the R4E production entry point, the R4G health command, and build-provenance behavior.

## R4H production source behavior

R4H production runs use native Windows certificate trust, bounded detail-source recovery, persisted last-known-good source locators, one bounded same-URL retry for a recently proven canonical source, and structured retry/recovery diagnostics.

A remembered source never produces `VERIFIED_OPEN` from stored metadata alone. Every successful verification still requires a current live fetch containing the expected procurement identity and satisfying the existing status/deadline verification contract.

If recent live proof exists but current direct/retry/recovery attempts end in `NOT_FOUND_CONFIRMED`, the result remains `DETAIL_UNAVAILABLE` and is classified as `PROVEN_SOURCE_TEMPORARILY_UNAVAILABLE` with degraded absence certainty. This prevents a single unstable EIS cycle from being treated as durable source disappearance while avoiding any cache-based false `VERIFIED_OPEN` result.

## Telegram credentials

The production profile stores environment-variable names only:

```text
RADAR_TELEGRAM_BOT_TOKEN
RADAR_TELEGRAM_CHAT_ID
```

Real token/chat values must remain outside Git.

Telegram delivery is disabled by default in the tracked production profile. The workstation background runner enables it at execution time with `--send-telegram-alerts`; preflight then requires the configured environment credentials to be available to that user session.

## Working-directory independence

R4E explicitly guarantees that the default production config and project-relative production DB/output paths do not depend on the caller's current working directory.

This behavior is covered by an offline regression test that changes the process CWD to an unrelated temporary directory, runs the normal production preflight entry point, and verifies that the production config and runtime directories resolve to the project base instead of the unrelated CWD.

R4G.6 also covers health-path resolution outside the project CWD so the read-only health check does not accidentally create or inspect a database relative to an unrelated caller directory.

Normal non-production CLI path semantics remain unchanged.

## Failure boundaries

Preflight occurs before recurring execution. Therefore an invalid production environment fails fast and does not start discovery or create a normal recurring `STARTED` lifecycle run.

After successful preflight, existing recurring guarantees remain in effect:

- overlapping Radar runs are locked out;
- stale Radar run locks can be recovered;
- failed runs do not replace the last successful published result;
- alert filtering remains deterministic;
- Telegram delivery remains optional and independently retryable.

The outer Windows background loop has a separate singleton lock and does not replace the inner Radar run lock.

## Windows production wrapper

The tracked CMD launcher is:

```text
scripts\radar-production.cmd
```

It resolves the project root from its own location, explicitly uses the repository `.venv`, writes timestamped logs to `runtime-logs/`, passes CLI arguments through to the runner, and preserves the exact Radar exit code.

The current recurrence mechanism is implemented outside the Python runtime by:

```text
scripts\radar-background-loop.ps1
scripts\install-radar-startup.ps1
```

The Startup installer creates/updates one passwordless current-user Startup shortcut. The background loop invokes the normal production launcher, waits for completion, and repeats on a three-hour interval while the user session exists.

See [Windows deployment](RADAR_WINDOWS_DEPLOYMENT.md) for the validated deployment contract and operational evidence.

## Validation

R4E itself was accepted with `176 passed`.

Tests at that milestone covered:

- valid production preflight;
- missing Telegram environment values when delivery is enabled;
- invalid runtime path handling;
- invalid operational values;
- routing through recurring orchestration;
- secret-safe preflight errors;
- fail-fast `--preflight-only` behavior;
- working-directory-independent production config/runtime path resolution.

Subsequent operational hardening has reached an accepted local suite of `297 passed`. The R4H source-resilience line was also validated with real production runs: stored live-proven canonical URLs were reused across cycles, same-URL proven retries were observed through structured diagnostics, repeated HTTP `404` responses were seen for recently verified sources, later resolver attempts sometimes recovered those procurements live, and unresolved recent-proof cases were correctly downgraded to `PROVEN_SOURCE_TEMPORARILY_UNAVAILABLE` rather than durable `SOURCE_URL_NOT_FOUND`.

## Scope boundary

R4E defines the stable Python production contract; it does not itself decide how Windows starts recurring executions.

The current supported workstation recurrence layer is the Startup/background-loop deployment. Task Scheduler is no longer the tracked production mechanism.

The health command remains intentionally local and read-only. It does not add an external monitoring service, notification channel, dashboard, or Windows service.
