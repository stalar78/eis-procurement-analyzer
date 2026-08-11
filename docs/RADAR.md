# EIS Procurement Radar

## Purpose

EIS Procurement Radar is the stateful decision-support layer of EIS Procurement Analyzer. It turns live EIS search results into a bounded, explainable pipeline for identifying procurements worth manual review, tracking meaningful changes across recurring runs, surfacing a compact alert feed, optionally delivering that feed to Telegram, and running through a stable Windows production launcher.

Current Radar version: `0.4.6-r4f1-state-guardrails`.

The Radar is intentionally conservative. It does not submit applications or replace legal/commercial review.

## End-to-end flow

```text
Windows production launcher / production preflight
    -> recurring orchestration / lock
    -> active EIS discovery
    -> deduplication and state
    -> provisional eligibility/scoring
    -> detail-page open verification
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

`PROCUREMENT_CLOSED` now requires an explicit observed transition into a supported closed status, including `closed`, `completed`, `cancelled`, or contract-signed equivalents.

Opportunity state follows the same rule. `OPPORTUNITY_NO_LONGER_ACTIVE` is emitted only from an explicit opportunity transition and is not inferred merely because the procurement or opportunity was absent from the latest bounded run.

### Recurring orchestration

R4B adds atomic `radar.lock` acquisition, stale-lock recovery, lifecycle statuses `STARTED`, `SUCCESS`, `FAILED`, and `SKIPPED_LOCKED`, failure isolation, and bounded retention.

### Alert filtering

R4C adds `radar.alerts`, which promotes high-value changes, suppresses noise, assigns alert priority, deduplicates multiple events for the same procurement, and stores alert fingerprints so identical alerts are not re-emitted.

R4F.1 ensures absence-only cases never create closure/inactivity source events, so they cannot be promoted into alerts downstream.

### Telegram delivery

R4D adds `radar.telegram_delivery`, an optional outbound-only adapter. It consumes only the filtered `alert_feed`, uses environment-based credentials by default, persists alert- and chunk-level delivery state, and retries transient failures without resending chunks already delivered successfully.

Because Telegram receives only filtered alerts, the R4F.1 transition guardrail also prevents absence-only cases from reaching the delivery adapter.

### Production profile and preflight

R4E adds `--production`, `config/radar.production.yaml`, stable project-root path resolution, and `--preflight-only`. Production preflight validates config readability, runtime directory writability, operational values, and Telegram credential availability when Telegram is enabled. Preflight failure returns exit code `78` without starting the Radar pipeline.

### Windows deployment support

R4F adds `scripts/radar-production.cmd` and `radar.windows_deployment`.

The launcher:

- derives the project root from its own location rather than the current working directory;
- explicitly uses the project's `.venv\Scripts\python.exe`;
- invokes the existing `radar.runner --production` path rather than implementing another runtime pipeline;
- supports normal production execution and `--preflight-only` passthrough;
- redirects stdout/stderr to timestamped files under `runtime-logs/`;
- preserves the exact Radar process exit code.

Task Scheduler must use the absolute local path to the launcher as `Program/script`. This path is a machine deployment value and is deliberately not hardcoded into tracked files. `Start in` is optional because the launcher resolves the project root itself.

## Windows launcher examples

Preflight:

```powershell
scripts\radar-production.cmd --preflight-only
```

Production run:

```powershell
scripts\radar-production.cmd
```

Task Scheduler shape:

```text
Program/script: <absolute-local-project-path>\scripts\radar-production.cmd
Arguments:      (empty)
Start in:       optional
```

Preflight task/check:

```text
Arguments: --preflight-only
```

## Configuration and secrets

Tracked production config: `config/radar.production.yaml`.

Telegram credentials remain environment-based:

```text
RADAR_TELEGRAM_BOT_TOKEN
RADAR_TELEGRAM_CHAT_ID
```

The launcher does not pass credentials on the command line. Real credentials must remain outside Git.

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

R4F.1 deterministic tests cover:

- a previously open procurement omitted from a later bounded run does not emit `PROCUREMENT_CLOSED`;
- an omitted opportunity does not emit `OPPORTUNITY_NO_LONGER_ACTIVE`;
- an explicit observed closed status still emits `PROCUREMENT_CLOSED`;
- an explicit inactivity transition still emits `OPPORTUNITY_NO_LONGER_ACTIVE`;
- absence-only cases produce no alert;
- absence-only cases trigger no Telegram HTTP call.

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
