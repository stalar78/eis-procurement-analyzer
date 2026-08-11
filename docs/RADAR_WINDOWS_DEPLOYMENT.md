# R4F Windows Deployment Support

R4F provides the Windows-side runtime contract needed to launch EIS Procurement Radar reliably from Windows Task Scheduler without embedding machine-specific paths or secrets in the repository.

## Launcher

Tracked launcher:

```text
scripts/radar-production.cmd
```

The launcher resolves the repository root from its own file location, explicitly uses `.venv\Scripts\python.exe`, enters the project root, and invokes:

```text
python -m radar.runner --production
```

Any launcher arguments are passed through to `radar.runner`, so deployment validation can use `--preflight-only` without creating a separate execution path.

## Working-directory independence

The launcher does not depend on the caller's current working directory. This is important for Windows Task Scheduler, which may start processes with an unexpected working directory.

The launcher derives the project root from `%~dp0` and therefore finds the virtual environment and production config relative to the checkout itself.

## Task Scheduler contract

Use the absolute local launcher path when creating the scheduled task:

```text
Program/script: <absolute-local-project-path>\scripts\radar-production.cmd
Arguments:      (empty for a normal production run)
Start in:       optional
```

For a deployment/preflight check:

```text
Arguments: --preflight-only
```

The absolute local repository path is deployment-specific and must not be committed to the repository.

## Exit codes

The CMD launcher captures `%ERRORLEVEL%` immediately after Radar exits and returns that same value with `exit /b`.

This preserves operational meanings already defined by Radar, including preflight failure exit code `78` and the existing recurring orchestration exit codes.

## Runtime logs

Each launcher execution writes stdout and stderr to:

```text
runtime-logs\radar-YYYYMMDD-HHMMSS.log
```

The directory is created locally when needed and is ignored by Git.

Launcher and preflight failures remain visible in these logs. Runtime logging must not contain Telegram credentials or other secret values.

## Secrets

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

The scheduled task must run in a Windows user/security context that can see the configured environment variables.

## Preflight before scheduling

Run the launcher manually before creating/enabling the real scheduled task:

```powershell
scripts\radar-production.cmd --preflight-only
```

A successful preflight should return exit code `0`. Failure returns a non-zero code and the detailed sanitized diagnostics are written to `runtime-logs/`.

## Runtime artifacts

R4F adds narrow ignore rules for:

```text
runtime-logs/
RADAR_R3A1_LIVE_VALIDATION.md
```

`RADAR_R3A1_LIVE_VALIDATION.md` is produced by the historical live-validation runtime path and is not project documentation. The ignore rule intentionally targets only that exact file.

## Validation

R4F was accepted with `181 passed`.

Tests cover:

- launcher project-root resolution from an unrelated current working directory;
- use of the project virtualenv Python;
- absolute Task Scheduler launcher-path generation;
- optional `Start in` semantics;
- exact preflight exit-code propagation;
- timestamped runtime logging;
- no duplicate `--production` argument in preflight mode;
- the narrow ignore rule for the live-validation runtime artifact.

## Boundary

R4F does **not** automatically register or modify Windows Task Scheduler tasks. Actual task creation, chosen schedule, Windows user context, and local environment-variable setup are deployment operations performed after the code milestone.
