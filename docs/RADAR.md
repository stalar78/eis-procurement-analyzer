# EIS Procurement Radar

## Purpose

EIS Procurement Radar is the stateful decision-support layer of EIS Procurement Analyzer. It turns live EIS search results into a bounded, explainable pipeline for identifying procurements worth manual review, tracking meaningful changes across recurring runs, surfacing a compact alert feed, and optionally delivering that feed to Telegram.

Current Radar version: `0.4.3-r4d-telegram-delivery`.

The Radar is intentionally conservative. It does not submit applications or replace legal/commercial review.

## End-to-end flow

```text
recurring orchestration / lock
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

## Main layers

### Discovery

`radar.discovery`, `radar.search_request`, `radar.search_profiles`, and `radar.open_verification` discover candidate procurements and distinguish currently open procedures from completed, cancelled, unknown, or conflicting states.

The default live mode is `ACTIVE_ONLY`. Failed-history discovery is separate and uses its own historical search window.

### Preliminary scoring

`radar.prefilter` and `radar.scoring` apply configurable rule-based filters and scores. Technical interest, budget, deadline, complexity, data quality, commodity risk, and negative platform/security signals are handled separately.

Decisions include `PRIORITY`, `REVIEW`, `WATCH`, `REJECT`, and `INSUFFICIENT_DATA`.

### Historical intelligence

`radar.historical`, `radar.analog_search`, `radar.competition_metrics`, and `radar.result_extraction` search completed procurements, select explainable analogs, resolve result/protocol evidence, and calculate competition metrics.

Historical evidence adjusts but does not overwrite the preliminary assessment.

### Failed-procurement opportunities

`radar.opportunities` adds evidence-backed historical failure classification, bounded failed-history discovery, republication matching, and a separate opportunity score.

### Recurring change feed

R4A reuses the existing SQLite state rather than introducing a parallel persistence model. Each saved run can emit `ChangeFeedEvent` records only for meaningful transitions.

Examples include `NEW_PROCUREMENT`, deadline/NMCK/status changes, score/decision changes, `PROCUREMENT_CLOSED`, `NEW_OPPORTUNITY`, `OPPORTUNITY_UPDATED`, and `OPPORTUNITY_NO_LONGER_ACTIVE`.

Repeated identical runs are idempotent and should emit no change-feed noise.

### Recurring orchestration

R4B adds the operational shell needed for unattended external scheduling.

`radar.orchestration` provides atomic `radar.lock` acquisition, stale-lock recovery, distinct exit codes, and bounded retention. `radar.state` stores append-only lifecycle statuses `STARTED`, `SUCCESS`, `FAILED`, and `SKIPPED_LOCKED`.

A failed recurring run does not replace the last successful published result, and lock release is handled through the failure path so a later run can continue normally.

### Alert filtering

R4C adds `radar.alerts`, a deterministic layer between the raw change feed and outbound delivery.

It promotes high-value events, suppresses low-value noise, assigns alert priority, deduplicates multiple changes for the same procurement, and stores alert fingerprints in SQLite `alert_history` so identical alerts are not re-emitted.

### Telegram delivery

R4D adds `radar.telegram_delivery`, an optional outbound-only adapter.

The adapter receives the already-filtered `alert_feed`; it does not repeat business scoring or filtering. It formats concise Telegram messages, splits long payloads within the configured message-size limit, sends through the Telegram Bot API over HTTPS, and records delivery state in SQLite.

Credentials are resolved from environment variables by default:

```text
RADAR_TELEGRAM_BOT_TOKEN
RADAR_TELEGRAM_CHAT_ID
```

Delivery is disabled by default. Real credentials must not be committed.

Successful alert delivery is deduplicated by alert fingerprint, channel, and chat destination. Failed attempts remain retryable. Multi-part messages are also persisted in `alert_delivery_chunks`: if an early chunk succeeds and a later chunk fails, the next retry skips already delivered chunks and sends only the remaining parts. Alert-level `SENT` is recorded only after all chunks have succeeded.

Transient failures use bounded retries with short backoff; permanent HTTP failures stop retrying within that attempt. Telegram delivery failure does not invalidate Radar state or the last successful published report.

### Enrichment

`radar.enrichment`, `radar.live_collection`, `radar.artifact_registry`, and `radar.deep_assessment` download bounded sets of procurement documents for selected candidates and run the document analyzer.

### State and resilience

`radar.state` stores procurement, assessment, opportunity, transition, change-feed, recurring-run lifecycle, alert-history, and alert-delivery data in SQLite.

`radar.source_resolution` provides bounded recovery when EIS URLs are stale or intermittently unavailable.

### Reporting

`radar.reporting` writes structured reports and supports transactional publication. The latest attempted run and last publishable successful result remain separable.

The raw change feed and filtered alert feed are available in runtime reporting surfaces. Telegram delivery consumes only the filtered feed.

## Configuration

Primary examples:

- `config/radar.example.yaml`
- `config/search_profiles.yaml`

R4B adds a `recurring` block, R4C adds an `alerts` block, and R4D adds a `telegram` block for optional delivery settings, retry limits, timeouts, environment variable names, and maximum message length.

## Core CLI

```powershell
.\.venv\Scripts\python.exe -m radar.runner --help
```

Recurring mode is enabled with `--recurring`. Telegram delivery can be explicitly enabled or disabled through the current CLI/config surface. The Radar does not contain an internal cron loop; an external scheduler should invoke it at the desired interval.

## Decision philosophy

The Radar separates evidence, alerting, and delivery layers deliberately:

- a technically attractive procurement can still have poor historical economics;
- missing historical data is not a rejection signal;
- historical failure is not automatically a positive signal;
- a current procurement must still be open and technically eligible;
- recurring monitoring should surface meaningful changes rather than repeat unchanged cards;
- alert filtering should surface high-value changes rather than forward the complete raw feed;
- delivery adapters should transmit approved alerts, not make business decisions;
- a failed delivery must not corrupt the analytical state or last useful report;
- overlapping recurring runs should be skipped rather than executed concurrently;
- low-confidence metrics remain low-confidence in the final report.

## Validation status

R3B.1 validated the live failed-history path against real EIS data.

R4A was accepted with `151 passed` and demonstrated idempotent two-run state comparison.

R4B was accepted with `156 passed`; deterministic tests cover locking, stale-lock recovery, failure recovery, lifecycle persistence, and retention.

R4C was accepted with `161 passed`; tests cover alert promotion, noise suppression, priority transition, urgent deadlines, deduplication, and repeated-run alert idempotency.

R4D was accepted with `168 passed`. Mocked Telegram tests cover successful delivery, duplicate suppression, retryable failure, transient retry, message splitting, disabled delivery, and partial multi-chunk recovery without resending already successful chunks.

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
