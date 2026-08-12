# EIS Procurement Radar

## Purpose

EIS Procurement Radar is the stateful decision-support layer of EIS Procurement Analyzer. It turns live EIS search results into a bounded, explainable pipeline for identifying procurements worth manual review, tracking meaningful changes across recurring runs, surfacing a compact alert feed, optionally delivering that feed to Telegram, and running through a stable Windows production launcher and Task Scheduler deployment.

Current Radar version: `0.4.8-r4f3-detail-verification-degradation`.

The Radar is intentionally conservative. It does not submit applications or replace legal/commercial review.

## End-to-end flow

```text
Windows production launcher / production preflight / Task Scheduler
    -> recurring orchestration / lock
    -> active EIS discovery
    -> deduplication and state
    -> provisional eligibility/scoring
    -> detail-page open verification with degradation policy
    -> historical analog search
    -> historical result/protocol extraction
    -> competition metrics + confidence
    -> history-adjusted assessment
    -> failed-procurement / republication opportunity intelligence
    -> recurring-state comparison / evidence-based transitions
    -> change feed
    -> alert filtering / deduplication / priority
    -> optional Telegram delivery
    -> controlled document enrichment
    -> deep assessment
    -> transactional publication
    -> lifecycle record + retention
```

## Operational layers

### Recurring change feed

R4A reuses the existing SQLite state and emits meaningful `ChangeFeedEvent` transitions rather than repeating unchanged observations.

R4F.1 tightens the transition contract: absence from a bounded run is not business-state evidence. A previously seen procurement that is missing from the next run remains previously observed state; it is not automatically marked closed.

`PROCUREMENT_CLOSED` requires an explicit observed transition into a supported closed status, including `closed`, `completed`, `cancelled`, or contract-signed equivalents.

Opportunity state follows the same rule. `OPPORTUNITY_NO_LONGER_ACTIVE` is emitted only from an explicit opportunity transition and is not inferred merely because the procurement or opportunity was absent from the latest bounded run.

### Recurring orchestration and recovery

R4B adds atomic `radar.lock` acquisition, stale-lock recovery, lifecycle statuses `STARTED`, `SUCCESS`, `FAILED`, and `SKIPPED_LOCKED`, failure isolation, and bounded retention.

R4F.2 strengthens Windows recovery for interrupted runs. When an existing lock contains a PID that is provably no longer alive, Radar can recover the orphan lock immediately instead of waiting for the age timeout. Live PIDs remain protected, and missing/malformed/indeterminate PID cases keep the conservative age-based fallback.

### Live detail verification

R4F.3 separates unavailable verification from negative verification evidence. A provisionally-open candidate is kept when detail verification returns `DETAIL_UNAVAILABLE` or when the candidate lies beyond the configured verification limit. `VERIFIED_CLOSED`, `VERIFIED_CANCELLED`, `STATUS_CONFLICT`, and `DEADLINE_CONFLICT` remain rejecting outcomes.

This prevents temporary detail-page/network unavailability from erasing otherwise valid active-search evidence without falsely converting unavailability into `VERIFIED_OPEN`.

### Alert filtering

R4C adds `radar.alerts`, which promotes high-value changes, suppresses noise, assigns alert priority, deduplicates multiple events for the same procurement, and stores alert fingerprints so identical alerts are not re-emitted.

R4F.1 ensures absence-only cases never create closure/inactivity source events, so they cannot be promoted into alerts downstream.

### Telegram delivery

R4D adds `radar.telegram_delivery`, an optional outbound-only adapter. It consumes only the filtered `alert_feed`, uses environment-based credentials by default, persists alert- and chunk-level delivery state, and retries transient failures without resending chunks already delivered successfully.

The Telegram path has been validated with a controlled live end-to-end run: active EIS discovery produced 13 candidates and 13 change events, a temporary isolated test threshold selected 4 alerts, and all 4 were delivered successfully. Production thresholds were not changed by that validation.

R4F.2.1 also isolates tests from host Telegram environment variables so local real/test credentials cannot alter deterministic test behavior or leak into assertion output.

### Production profile and preflight

R4E adds `--production`, `config/radar.production.yaml`, stable project-root path resolution, and `--preflight-only`. Production preflight validates config readability, runtime directory writability, operational values, and Telegram credential availability when Telegram is enabled. Preflight failure returns exit code `78` without starting the Radar pipeline.

### Windows deployment support

R4F adds `scripts/radar-production.cmd`. The current repository also includes `scripts/register-radar-task.ps1` for idempotent registration/update of the local scheduled task.

The launcher:

- derives the project root from its own location rather than the current working directory;
- explicitly uses the project's `.venv\Scripts\python.exe`;
- invokes the existing `radar.runner --production` path rather than implementing another runtime pipeline;
- supports normal production execution and CLI passthrough such as `--preflight-only` or `--send-telegram-alerts`;
- redirects stdout/stderr to timestamped files under `runtime-logs/`;
- preserves the exact Radar process exit code.

The registration script creates/updates `Stalar Procurement Radar`, schedules it every three hours, uses the repository root as the working directory, passes only `--send-telegram-alerts`, and configures Task Scheduler to ignore overlapping starts while Radar's own lock remains the second line of protection.

The current task registration uses the current Windows user with interactive logon semantics and has been manually validated through Task Scheduler with result code `0` and no residual `radar.lock`.

## Windows launcher examples

Preflight:

```powershell
scripts\radar-production.cmd --preflight-only --verbose --send-telegram-alerts
```

Production run:

```powershell
scripts\radar-production.cmd --send-telegram-alerts
```

Register/update the scheduled task:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register-radar-task.ps1
```

## Configuration and secrets

Tracked production config: `config/radar.production.yaml`.

Telegram credentials remain environment-based:

```text
RADAR_TELEGRAM_BOT_TOKEN
RADAR_TELEGRAM_CHAT_ID
```

The launcher and scheduler registration do not pass credential values on the command line. Real credentials must remain outside Git.

## Runtime data

`runtime-logs/` is local runtime output and is ignored by Git. `RADAR_R3A1_LIVE_VALIDATION.md` is also ignored narrowly because `radar.historical_live_validation` creates it as a root-level runtime validation artifact. The ignore rule does not cover general Markdown documentation.

## Validation status

- R4A: `151 passed`
- R4B: `156 passed`
- R4C: `161 passed`
- R4D: `168 passed`
- R4E: `176 passed`
- R4F: `181 passed`
- R4F.1: `183 passed`
- R4F.2 / R4F.2.1 / R4F.3 accepted suite: `193 passed`

R4F.3 validation covers, among other cases:

- absence-only procurement/opportunity observations do not become closure/inactivity evidence;
- explicit closure/inactivity evidence still produces the supported transitions;
- Windows dead-PID locks are recoverable while live-PID locks remain protected;
- host Telegram environment credentials are isolated from tests;
- `DETAIL_UNAVAILABLE` preserves a provisionally-open candidate;
- `VERIFIED_OPEN` preserves a candidate;
- verified closed/cancelled candidates are removed;
- candidates beyond the detail-verification limit are not dropped;
- diagnostics preserve unavailable/skipped/rejected verification information.

## Safety and repository hygiene

Real procurement documents, live HTML, SQLite state, generated reports, browser state, locks, Telegram credentials, runtime logs, and downloaded protocol artifacts are runtime data and must remain outside Git.

See also:

- [Live discovery](RADAR_LIVE_DISCOVERY.md)
- [Enrichment](RADAR_ENRICHMENT.md)
- [Historical intelligence](RADAR_HISTORICAL_INTELLIGENCE.md)
- [Resilience](RADAR_RESILIENCE.md)
- [Analog selection](RADAR_ANALOG_SELECTION.md)
- [Result extraction](RADAR_RESULT_EXTRACTION.md)
- [Opportunity intelligence](RADAR_OPPORTUNITIES.md)
- [Recurring change feed](RADAR_CHANGE_FEED.md)
- [Recurring orchestration](RADAR_ORCHESTRATION.md)
- [Alert filtering](RADAR_ALERTS.md)
- [Telegram delivery](RADAR_TELEGRAM.md)
- [Production profile](RADAR_PRODUCTION.md)
- [Windows deployment](RADAR_WINDOWS_DEPLOYMENT.md)
- [State-transition guardrails](RADAR_STATE_GUARDRAILS.md)
