# EIS Procurement Radar

## Purpose

EIS Procurement Radar is the stateful decision-support layer of EIS Procurement Analyzer. It turns live EIS search results into a bounded, explainable pipeline for identifying procurements worth manual review and tracking meaningful changes across recurring runs.

Current Radar version: `0.4.1-r4b-orchestration`.

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

`radar.orchestration` provides:

- atomic `radar.lock` acquisition for recurring runs;
- stale-lock recovery after a configurable timeout;
- distinct success, locked/skipped, and failure exit codes;
- bounded retention for archived successful and failed runtime directories.

`radar.state` stores append-only recurring lifecycle records with statuses `STARTED`, `SUCCESS`, `FAILED`, and `SKIPPED_LOCKED`.

A failed recurring run does not replace the last successful published result, and lock release is handled through the failure path so a later run can continue normally.

### Enrichment

`radar.enrichment`, `radar.live_collection`, `radar.artifact_registry`, and `radar.deep_assessment` download bounded sets of procurement documents for selected candidates and run the document analyzer.

### State and resilience

`radar.state` stores procurement, assessment, opportunity, transition, change-feed, and recurring-run lifecycle data in SQLite.

`radar.source_resolution` provides bounded recovery when EIS URLs are stale or intermittently unavailable.

### Reporting

`radar.reporting` writes structured reports and supports transactional publication. The latest attempted run and last publishable successful result remain separable.

## Configuration

Primary examples:

- `config/radar.example.yaml`
- `config/search_profiles.yaml`

R4B adds a `recurring` configuration block for stale-lock timeout and successful/failed runtime retention counts.

## Core CLI

```powershell
.\.venv\Scripts\python.exe -m radar.runner --help
```

Recurring mode is enabled with `--recurring`. CLI overrides are available for stale-lock timeout and retention limits.

The Radar does not contain an internal cron loop; an external scheduler should invoke the recurring command at the desired interval.

## Decision philosophy

The Radar separates evidence layers deliberately:

- a technically attractive procurement can still have poor historical economics;
- missing historical data is not a rejection signal;
- historical failure is not automatically a positive signal;
- a current procurement must still be open and technically eligible;
- recurring monitoring should surface meaningful changes rather than repeat unchanged cards;
- a failed unattended run must not destroy the last useful published result;
- overlapping recurring runs should be skipped rather than executed concurrently;
- partial protocol evidence contributes only to the metric it supports;
- low-confidence metrics remain low-confidence in the final report.

## Validation status

R3B.1 validated the live failed-history path against real EIS data.

R4A was accepted with `151 passed` and demonstrated idempotent two-run state comparison.

R4B was accepted with `156 passed`. Deterministic orchestration tests cover locking, stale-lock recovery, failure recovery, lifecycle persistence, and retention. A two-run validation on one SQLite database produced `STARTED -> SUCCESS` twice, while the second identical run reported `new=0`, `changed=0`, and no change-feed events.

## Safety and repository hygiene

Real procurement documents, live HTML, SQLite state, generated reports, browser state, locks, and downloaded protocol artifacts are runtime data and must remain outside Git.

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
