# R4F Windows Deployment Support

R4F provides the Windows-side runtime contract needed to launch EIS Procurement Radar reliably from Windows Task Scheduler without embedding secrets in the repository. The deployment path has now been validated with a real scheduled execution.

## Launcher

Tracked launcher:

```text
scripts/radar-production.cmd
```

The launcher resolves the repository root from its own file location, explicitly uses `.venv\Scripts\python.exe`, enters the project root, and invokes:

```text
python -m radar.runner --production
```

Any launcher arguments are passed through to `radar.runner`, so deployment validation can use `--preflight-only` and production delivery can use `--send-telegram-alerts` without creating separate runtime pipelines.

## Working-directory independence

The launcher does not depend on the caller's current working directory. This is important for Windows Task Scheduler, which may start processes with an unexpected working directory.

The launcher derives the project root from `%~dp0` and therefore finds the virtual environment and production config relative to the checkout itself.

## Task registration

Tracked registration helper:

```text
scripts/register-radar-task.ps1
```

The script is safe to rerun: `Register-ScheduledTask -Force` updates the same task rather than creating duplicates.

Default task name:

```text
Stalar Procurement Radar
```

The registered action uses:

```text
Program/script: <absolute-local-project-path>\scripts\radar-production.cmd
Arguments:      --send-telegram-alerts
Start in:       <absolute-local-project-path>
```

The absolute path is resolved locally by the registration script; it is not hardcoded in repository content.

Register/update from PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register-radar-task.ps1
```

## Schedule and concurrency

The current registration contract uses:

- repetition interval: every 3 hours;
- `StartWhenAvailable` for missed starts;
- `MultipleInstances IgnoreNew` to avoid overlapping Task Scheduler instances;
- the existing Radar lock as an additional process-level concurrency guard.

The task runs under the current Windows user with `LogonType Interactive` and `RunLevel Limited`.

This is intentionally a workstation-oriented deployment. It assumes the selected user session/security context is available and can see the configured user environment variables. It is not a service-account or unattended-server deployment mode.

## Telegram credentials

Telegram credentials remain external environment values:

```text
RADAR_TELEGRAM_BOT_TOKEN
RADAR_TELEGRAM_CHAT_ID
```

Do not place credentials in:

- the tracked launcher;
- `config/radar.production.yaml`;
- Task Scheduler command-line arguments;
- repository documentation or fixtures.

The scheduled task passes only `--send-telegram-alerts`; credential values are read from the process environment by Radar.

## Preflight before scheduling

Validate the launcher from the target Windows user context before relying on the schedule:

```powershell
scripts\radar-production.cmd --preflight-only --verbose --send-telegram-alerts
```

A successful preflight returns exit code `0`. Failure returns a non-zero code and sanitized diagnostics are written to `runtime-logs/`.

## Validated deployment result

The Task Scheduler registration has been exercised with a manual `Start-ScheduledTask` run.

Observed deployment result:

- registration/update succeeded;
- scheduled task state returned to `Ready`;
- manual scheduled run completed with result code `0`;
- Radar runtime log was produced under `runtime-logs/`;
- no residual `outputs/radar/radar.lock` remained after completion;
- the next three-hour trigger was scheduled normally.

A parser warning about a malformed/partial EIS search card can appear in runtime logs without making the scheduled run fail. Such warnings should be monitored for frequency and impact rather than treated as deployment failure by themselves.

## Exit codes

The CMD launcher captures `%ERRORLEVEL%` immediately after Radar exits and returns that same value with `exit /b`.

This preserves operational meanings already defined by Radar, including preflight failure exit code `78`, lock-related recurring codes, and success code `0`.

Task Scheduler therefore exposes the Radar/launcher result directly in `LastTaskResult`.

## Runtime logs

Each launcher execution writes stdout and stderr to:

```text
runtime-logs\radar-YYYYMMDD-HHMMSS.log
```

The directory is created locally when needed and is ignored by Git.

Launcher and preflight failures remain visible in these logs. Runtime logging must not contain Telegram credentials or other secret values.

## Runtime artifacts

Runtime logs, generated reports, SQLite state, locks, downloaded procurement materials, live EIS HTML/protocol data, and browser state remain local and must not be committed.

`RADAR_R3A1_LIVE_VALIDATION.md` remains narrowly ignored as a root-level historical live-validation runtime artifact rather than project documentation.

## Validation history

R4F code-level launcher support was accepted with `181 passed`.

Subsequent operational hardening added:

- R4F.1 evidence-based state transition guardrails;
- R4F.2 dead-PID orphan-lock recovery on Windows;
- R4F.2.1 isolation of tests from host Telegram environment credentials;
- R4F.3 detail-verification degradation semantics.

The accepted suite at R4F.3 is `193 passed`, followed by successful live Telegram and Task Scheduler validation.

## Boundary

The tracked registration helper configures the current workstation deployment only. Machine-specific task state, Windows credentials, Telegram secrets, Task Scheduler history, runtime logs, and generated Radar data remain external to Git.
