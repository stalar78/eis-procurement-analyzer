# EIS Procurement Radar

## Purpose

EIS Procurement Radar is the stateful decision-support layer of EIS Procurement Analyzer. It turns live EIS search results into a bounded, explainable pipeline for identifying procurements worth manual review, tracking meaningful changes across recurring runs, surfacing a compact alert feed, optionally delivering that feed to Telegram, and running through a stable Windows production launcher plus a passwordless current-user Startup background runner.

Current Radar version label: `0.4.8-r4f3-detail-verification-degradation`.

The Radar is intentionally conservative. It does not submit applications or replace legal/commercial review.

## End-to-end flow

```text
Windows login / Startup shortcut / background loop
    -> Windows production launcher / production preflight
    -> recurring orchestration / radar.lock
    -> active EIS discovery
    -> deduplication and state
    -> provisional eligibility/scoring
    -> detail-page evidence verification
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

R4F.2 strengthens Windows recovery for interrupted runs. When an existing Radar run lock contains a PID that is provably no longer alive, Radar can recover the orphan lock immediately instead of waiting for the age timeout. Live PIDs remain protected, and missing/malformed/indeterminate PID cases keep the conservative age-based fallback.

### Detail evidence verification

The current detail-verification contract is stricter than the original R4F.3 degradation rule.

A provisionally-open card can become `VERIFIED_OPEN` only when the fetched detail content provides all three required evidence elements:

- the expected procurement identity;
- an explicit active/open detail status;
- an explicit future application deadline.

The search-card status/deadline are no longer fallback evidence for missing detail fields. They may still be retained for comparison and conflict detection.

Incomplete, generic, malformed, wrong-procurement, or otherwise inconclusive detail content becomes `DETAIL_UNAVAILABLE` rather than self-confirming the original card. Explicit closed/cancelled detail evidence still produces `VERIFIED_CLOSED` / `VERIFIED_CANCELLED`; explicit conflicts remain conservative rejecting outcomes.

This preserves the R4F.3 degradation principle without weakening the meaning of `VERIFIED`.

### TLS source integrity

Production Radar HTTP retrieval uses normal `requests` certificate verification. Production EIS paths do not use `verify=False` and do not suppress insecure-request warnings.

TLS certificate failures cannot become valid evidence. Detail verification degrades to `DETAIL_UNAVAILABLE`; source resolution remains temporarily unavailable. The system does not retry by disabling certificate validation.

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

The active workstation deployment uses:

```text
scripts/radar-production.cmd
scripts/radar-background-loop.ps1
scripts/install-radar-startup.ps1
```

The CMD launcher:

- derives the project root from its own location rather than the current working directory;
- explicitly uses the project's `.venv\Scripts\python.exe`;
- invokes the existing `radar.runner --production` path rather than implementing another runtime pipeline;
- supports CLI passthrough such as `--preflight-only` or `--send-telegram-alerts`;
- redirects stdout/stderr to timestamped files under `runtime-logs/`;
- preserves the exact Radar process exit code.

The Startup installer creates/updates one current-user `.lnk` entry. It requires neither administrator rights nor a Windows password. The shortcut launches `radar-background-loop.ps1` hidden. The loop invokes `radar-production.cmd --send-telegram-alerts`, waits for the run to finish, then sleeps for three hours.

The background-loop singleton is separate from the inner Radar run lock. It uses atomic `CreateNew` acquisition and records PID, process start time, and a unique owner token. Dead, malformed, legacy, and PID-reused locks can be recovered; a live matching owner blocks a second runner with exit code `75`; cleanup removes only a lock still owned by the current process.

The previous Task Scheduler deployment is deprecated. Its registration helper has been removed from the repository and the old workstation task should remain disabled/removed.

## Windows launcher and Startup examples

Preflight:

```powershell
scripts\radar-production.cmd --preflight-only --verbose --send-telegram-alerts
```

One direct production run:

```powershell
scripts\radar-production.cmd --send-telegram-alerts
```

Install/update current-user Startup entry:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-radar-startup.ps1
```

Manual one-cycle background validation:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\radar-background-loop.ps1 -RunOnce
```

## Configuration and secrets

Tracked production config: `config/radar.production.yaml`.

Telegram credentials remain environment-based:

```text
RADAR_TELEGRAM_BOT_TOKEN
RADAR_TELEGRAM_CHAT_ID
```

The launcher, background loop, and Startup shortcut do not contain credential values. Real credentials must remain outside Git.

## Runtime data

`runtime-logs/` is local runtime output and is ignored by Git. `RADAR_R3A1_LIVE_VALIDATION.md` is also ignored narrowly because `radar.historical_live_validation` creates it as a root-level runtime validation artifact. The ignore rule does not cover general Markdown documentation.

## Validation status

Milestone history:

- R4A: `151 passed`
- R4B: `156 passed`
- R4C: `161 passed`
- R4D: `168 passed`
- R4E: `176 passed`
- R4F: `181 passed`
- R4F.1: `183 passed`
- R4F.2 / R4F.2.1 / R4F.3: `193 passed`
- detail-evidence hardening: `215 passed`
- TLS integrity hardening: `219 passed`
- background-runner hardening: `226 passed`

Operational validation additionally demonstrated:

- stale/legacy background-loop lock recovery in a real workstation runtime;
- successful direct background cycle with launcher exit code `0`;
- persistent loop remaining alive after a completed Radar cycle;
- actual Windows reboot/login automatically starting the Startup shortcut;
- a new post-login background owner with fresh PID/start-time/token metadata;
- automatic post-login Radar execution completing with launcher exit code `0`.

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
