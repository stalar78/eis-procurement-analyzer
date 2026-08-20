# Windows Deployment Support

The active Windows deployment for EIS Procurement Radar is a workstation-oriented, passwordless current-user Startup flow. It does not depend on Windows Task Scheduler, a stored Windows password, or administrator rights.

## Runtime chain

```text
Windows login
    -> current-user Startup shortcut
    -> hidden PowerShell background loop
    -> scripts\radar-production.cmd --send-telegram-alerts
    -> radar.runner --production
```

The deployment remains intentionally user-session based. It is not a Windows service or unattended server/service-account contract.

## Tracked deployment files

```text
scripts\radar-production.cmd
scripts\radar-background-loop.ps1
scripts\install-radar-startup.ps1
```

The old `scripts/register-radar-task.ps1` helper has been removed. Task Scheduler is no longer the supported production deployment path.

## Production launcher

`scripts\radar-production.cmd` resolves the repository root from its own file location, explicitly uses `.venv\Scripts\python.exe`, enters the project root, and invokes:

```text
python -m radar.runner --production
```

Launcher arguments are passed through to `radar.runner`, so production delivery can add `--send-telegram-alerts` and validation can use `--preflight-only` without introducing a second runtime implementation.

Each launcher execution writes stdout/stderr to:

```text
runtime-logs\radar-YYYYMMDD-HHMMSS.log
```

The launcher captures and returns the exact Radar exit code.

## Startup installer

Install or refresh the current-user Startup entry with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-radar-startup.ps1
```

The installer:

- resolves the project root from its own location;
- creates/updates one shortcut in `[Environment]::GetFolderPath("Startup")`;
- launches the system Windows PowerShell executable;
- passes `-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden`;
- starts `scripts\radar-background-loop.ps1`;
- uses the repository root as the working directory;
- is idempotent and does not create duplicate Startup entries;
- requires neither elevation nor a Windows password.

The shortcut contains no Telegram credentials or other secrets.

## Background loop

The background loop starts immediately, invokes:

```text
scripts\radar-production.cmd --send-telegram-alerts
```

waits for that Radar run to finish, logs the launcher exit code, and then sleeps for the default three-hour interval (`10800` seconds). A non-zero Radar launcher exit does not terminate the recurring loop; the next scheduled cycle is still attempted.

`-RunOnce` is supported for controlled validation:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\radar-background-loop.ps1 -RunOnce
```

## Background-loop singleton

The outer background loop has its own lock:

```text
runtime-logs\radar-background-loop.lock
```

This is separate from the inner recurring Radar lock at `outputs\radar\radar.lock`.

Lock acquisition is atomic using exclusive file creation. Lock metadata includes:

- PID;
- process start time;
- a unique owner token;
- startup timestamp;
- project root.

A lock is treated as belonging to a live loop only when the PID exists and the recorded process start time matches that process. This protects against PID reuse.

Dead, malformed, legacy, or mismatched-owner locks are recoverable. A genuinely live matching owner blocks a competing loop and causes the contender to exit with code `75`.

Cleanup is owner-safe: a process removes the lock only when PID, process start time, and owner token still identify that process as the current owner.

## Telegram credentials

Telegram credentials remain external environment values:

```text
RADAR_TELEGRAM_BOT_TOKEN
RADAR_TELEGRAM_CHAT_ID
```

Do not place credentials in:

- tracked scripts;
- `config/radar.production.yaml`;
- Startup shortcut arguments;
- repository documentation or fixtures.

The background loop passes only `--send-telegram-alerts`; credential values are read by Radar from the Windows user environment.

## Preflight

Validate the production environment directly with:

```powershell
.\.venv\Scripts\python.exe -m radar.runner --production --preflight-only --verbose
```

Or validate through the launcher:

```powershell
scripts\radar-production.cmd --preflight-only --verbose --send-telegram-alerts
```

A successful preflight returns exit code `0`. Preflight failure returns `78` and stops before normal recurring lifecycle execution.

## Operational validation

The Startup-based deployment has been validated on the target Windows workstation with real runtime evidence.

Confirmed sequence:

1. the Startup shortcut was present in the current-user Startup folder;
2. manual shortcut execution started exactly one hidden background-loop process;
3. the process acquired the hardened lock with PID/start-time/owner-token metadata;
4. an existing legacy/stale loop lock was recovered automatically;
5. Radar completed through the normal production launcher with exit code `0`;
6. the background process remained alive after the completed Radar cycle, waiting for the next three-hour cycle;
7. after an actual Windows reboot and login, the Startup shortcut launched the background loop automatically without manual intervention;
8. the post-login process had a fresh PID, start time, and owner token;
9. the reboot left the previous-session lock behind, and the new process recovered it as stale;
10. the post-login Radar cycle completed with launcher exit code `0`.

This validates the workstation deployment contract:

```text
Windows login -> Startup -> background loop -> production launcher -> Radar -> wait for next cycle
```

## Deprecated Task Scheduler path

The earlier `Stalar Procurement Radar` Task Scheduler deployment was retired after repeated interactive-session/control-interruption behavior. The registration helper has been removed from the repository.

Any pre-existing local Task Scheduler task should remain disabled or be removed so that only one production scheduling mechanism exists.

Do not reintroduce a password-backed, S4U, or interactive Task Scheduler path as a parallel production mechanism without a new explicit deployment decision and validation.

## Runtime logs and artifacts

Background-loop diagnostics are written to:

```text
runtime-logs\radar-background-loop.log
```

The current outer lock is:

```text
runtime-logs\radar-background-loop.lock
```

Normal Radar launcher logs remain:

```text
runtime-logs\radar-YYYYMMDD-HHMMSS.log
```

Runtime logs, generated reports, SQLite state, locks, downloaded procurement materials, live EIS HTML/protocol data, and browser state remain local and must not be committed.

## Validation history

Windows deployment evolved through several hardening steps. The accepted local test suite after the Startup/background-runner reliability work is `226 passed`.

Behavioral coverage includes:

- two concurrent loop processes, with exactly one owner and the other exiting `75`;
- dead/orphan lock recovery;
- malformed lock recovery;
- PID-reuse/start-time mismatch recovery;
- live matching owner rejection;
- owner-safe cleanup;
- `-RunOnce` cleanup;
- continued loop behavior after a non-zero Radar launcher exit.

The actual reboot/login validation complements these tests with workstation runtime evidence.

## Boundary and next hardening step

The deployment is validated for the current Windows workstation while the user is logged in. It is not intended to survive user logoff as a service.

Remote CI still needs a Windows job that executes the Windows-specific launcher/PowerShell behavior. That CI work is a separate hardening step and does not change the current workstation runtime contract.
