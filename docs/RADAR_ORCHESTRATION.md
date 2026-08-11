# R4B Recurring Orchestration

R4B adds a small operational shell around the existing Radar pipeline so it can be invoked safely by an external scheduler.

Current Radar version: `0.4.1-r4b-orchestration`.

## Scope

R4B does not install or manage a scheduler and does not add an internal cron loop. It makes one recurring invocation safe and predictable.

## Run locking

Recurring mode uses `radar.lock` in the configured runtime output directory.

The lock is created atomically. If another active recurring run already holds it, the new invocation is recorded as `SKIPPED_LOCKED` and exits with code `75` instead of running concurrently.

A lock older than the configured stale timeout can be recovered. Recovery is recorded in lifecycle diagnostics.

## Run lifecycle

SQLite stores append-only recurring lifecycle records with:

- run identifier;
- status;
- start/finish timestamps;
- failure reason when applicable;
- lock path;
- diagnostics.

Statuses are:

- `STARTED`;
- `SUCCESS`;
- `FAILED`;
- `SKIPPED_LOCKED`.

## Failure isolation

Recurring failures are recorded and return a failure exit code without replacing the last successfully published result.

The run lock is released through the `finally` path, so a subsequent invocation can proceed normally after a failure.

## Exit codes

- `0` — success;
- `75` — skipped because another recurring run holds the lock;
- `1` — recurring run failure.

## Retention

R4B can bound archived runtime storage separately for successful and failed run directories.

Retention targets archived directories under `runs/` and `runs_failed/`. Current publication pointers such as `latest.json`, `latest.md`, `latest.xlsx`, and `latest_attempt.json` are not retention targets.

Temporary `.tmp` run directories are not treated as archived successful runs.

## Configuration

The example configuration contains:

```yaml
recurring:
  lock_stale_after_minutes: 120
  retain_successful_runs: 30
  retain_failed_runs: 30
```

Equivalent CLI overrides are available for stale-lock timeout and retention counts. Use `python -m radar.runner --help` as the source of truth for current option names.

## External scheduling

A scheduler such as Windows Task Scheduler may invoke the normal Radar command with `--recurring` and the same persistent SQLite database/output directory on each run.

R4B deliberately keeps scheduling outside the application so operational policy remains separate from the analytical pipeline.

## Validation

R4B was accepted with `156 passed` in the full local test suite.

Deterministic tests cover active locks, stale-lock recovery, failed-run recording/recovery, lifecycle persistence, and runtime retention.

A two-run validation using the same SQLite database completed `STARTED -> SUCCESS` twice; the identical second run produced zero new procurements, zero changed procurements, and no change-feed events.

## Current boundary

R4B makes recurring execution reliable but does not yet decide which change-feed events deserve a user-facing alert and does not send Telegram/email notifications.
