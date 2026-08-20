# R4E Production Profile

## Purpose

R4E adds a stable production-style entry point for recurring EIS Procurement Radar runs. The goal is to make the runtime predictable for an external Windows launcher/background runner without embedding scheduling policy inside the Python application.

Current R4E milestone label: `0.4.4-r4e-production-profile`.

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

Subsequent operational hardening reached an accepted local suite of `226 passed` and added stricter detail evidence, TLS verification, and behavioral Windows background-runner coverage without changing the core R4E production entry point.

## Scope boundary

R4E defines the stable Python production contract; it does not itself decide how Windows starts recurring executions.

The current supported workstation recurrence layer is the Startup/background-loop deployment. Task Scheduler is no longer the tracked production mechanism.
