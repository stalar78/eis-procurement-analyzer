# EIS Procurement Radar

## Purpose

EIS Procurement Radar is the stateful decision-support layer of EIS Procurement Analyzer. It turns live EIS search results into a bounded, explainable pipeline for identifying procurements worth manual review, tracking meaningful changes across recurring runs, surfacing a compact alert feed, optionally delivering that feed to Telegram, and running through a stable production-style entry point.

Current Radar version: `0.4.4-r4e-production-profile`.

The Radar is intentionally conservative. It does not submit applications or replace legal/commercial review.

## End-to-end flow

```text
production profile / preflight
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
    -> recurring-state comparison / change feed
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

### Recurring orchestration

R4B adds atomic `radar.lock` acquisition, stale-lock recovery, lifecycle statuses `STARTED`, `SUCCESS`, `FAILED`, and `SKIPPED_LOCKED`, failure isolation, and bounded retention.

### Alert filtering

R4C adds `radar.alerts`, which promotes high-value changes, suppresses noise, assigns alert priority, deduplicates multiple events for the same procurement, and stores alert fingerprints so identical alerts are not re-emitted.

### Telegram delivery

R4D adds `radar.telegram_delivery`, an optional outbound-only adapter. It consumes only the filtered `alert_feed`, uses environment-based credentials by default, persists alert- and chunk-level delivery state, and retries transient failures without resending chunks already delivered successfully.

### Production profile and preflight

R4E adds a stable production entry point intended for external schedulers.

`--production` uses `config/radar.production.yaml` by default and automatically enables the existing recurring orchestration path. The default production config is resolved from the project root rather than the current working directory.

Relative production runtime paths such as the SQLite DB and output directory are normalized against the project root, so Task Scheduler or another caller can launch the program from an unrelated working directory without redirecting state into that directory.

`--preflight-only` validates the production environment without starting the pipeline. Current preflight checks include:

- production config is readable;
- SQLite parent directory is writable or safely creatable;
- output directory is writable or safely creatable;
- recurring retention and stale-lock values are valid;
- Telegram timeout/retry/message-size values are valid;
- Telegram credentials are present when Telegram delivery is enabled.

Preflight failure returns exit code `78` and does not start the Radar pipeline.

Preflight error output is designed not to expose secret values. Real Telegram credentials must remain outside Git.

## Production CLI

Preflight:

```powershell
.\.venv\Scripts\python.exe -m radar.runner --production --preflight-only --verbose
```

Recurring production run:

```powershell
.\.venv\Scripts\python.exe -m radar.runner --production
```

The application does not contain an internal scheduler loop. Windows Task Scheduler, cron, or another external scheduler should invoke the production command at the desired interval.

## Configuration

Primary tracked configuration files:

- `config/radar.example.yaml` — general example configuration;
- `config/radar.production.yaml` — stable production-oriented profile;
- `config/search_profiles.yaml` — discovery search profiles.

The production profile intentionally contains project-relative paths and environment-variable names rather than machine-specific absolute paths or secrets.

Telegram environment variables:

```text
RADAR_TELEGRAM_BOT_TOKEN
RADAR_TELEGRAM_CHAT_ID
```

Telegram remains disabled in the tracked production profile until explicitly enabled.

## State and failure behavior

`radar.state` stores procurement, assessment, opportunity, change-feed, recurring lifecycle, alert-history, and alert-delivery data in SQLite.

Production preflight runs before recurring orchestration. A failed preflight does not create a recurring lifecycle run and does not start discovery. Once preflight succeeds, the normal R4B locking/lifecycle semantics remain unchanged.

Telegram delivery failure does not invalidate Radar state or the last successfully published report.

## Validation status

- R4A: `151 passed`
- R4B: `156 passed`
- R4C: `161 passed`
- R4D: `168 passed`
- R4E: `176 passed`

R4E deterministic tests cover valid preflight, missing Telegram environment values when delivery is enabled, invalid runtime paths, invalid config values, production routing through recurring orchestration, secret-safe errors, fail-fast preflight, and production execution from an unrelated current working directory.

## Safety and repository hygiene

Real procurement documents, live HTML, SQLite state, generated reports, browser state, locks, Telegram credentials, and downloaded protocol artifacts are runtime data and must remain outside Git.

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
