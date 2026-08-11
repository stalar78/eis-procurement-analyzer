# R4E Production Profile

## Purpose

R4E adds a stable production-style entry point for recurring EIS Procurement Radar runs. The goal is to make the runtime predictable for Windows Task Scheduler or another external scheduler without embedding scheduling logic inside the application.

Current milestone: `0.4.4-r4e-production-profile`.

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

In production/preflight mode these paths are normalized against the project root. This prevents an external scheduler launched from a directory such as `C:\Windows\System32` from accidentally creating Radar state relative to that directory.

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

## Telegram credentials

The production profile stores environment-variable names only:

```text
RADAR_TELEGRAM_BOT_TOKEN
RADAR_TELEGRAM_CHAT_ID
```

Real token/chat values must remain outside Git.

Telegram delivery is disabled by default in the tracked production profile. If it is enabled, preflight fails when required credentials are unavailable.

## Working-directory independence

R4E explicitly guarantees that the default production config and project-relative production DB/output paths do not depend on the caller's current working directory.

This behavior is covered by an offline regression test that changes the process CWD to an unrelated temporary directory, runs the normal production preflight entry point, and verifies that the production config and runtime directories resolve to the project base instead of the unrelated CWD.

Normal non-production CLI path semantics remain unchanged.

## Failure boundaries

Preflight occurs before recurring execution. Therefore an invalid production environment fails fast and does not start discovery or create a normal recurring `STARTED` lifecycle run.

After successful preflight, existing R4B-R4D guarantees remain in effect:

- overlapping recurring runs are locked out;
- stale locks can be recovered;
- failed runs do not replace the last successful published result;
- alert filtering remains deterministic;
- Telegram delivery remains optional and independently retryable.

## Validation

R4E was accepted with `176 passed`.

Tests cover:

- valid production preflight;
- missing Telegram environment values when delivery is enabled;
- invalid runtime path handling;
- invalid operational values;
- routing through recurring orchestration;
- secret-safe preflight errors;
- fail-fast `--preflight-only` behavior;
- working-directory-independent production config/runtime path resolution.

## Scope boundary

R4E does not create or register a Windows Task Scheduler task. It provides the stable runtime contract that such a task can invoke.

The next deployment step can therefore focus only on Task Scheduler registration, environment setup, schedule choice, and first controlled scheduled execution without changing Radar business logic.
