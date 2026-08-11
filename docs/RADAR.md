# EIS Procurement Radar

## Purpose

EIS Procurement Radar is the stateful decision-support layer of EIS Procurement Analyzer. It turns live EIS search results into a bounded, explainable pipeline for identifying procurements worth manual review and tracking meaningful changes across recurring runs.

Current Radar version: `0.4.0-r4a-change-feed`.

The Radar is intentionally conservative. It does not submit applications or replace legal/commercial review.

## End-to-end flow

```text
active EIS discovery
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
    -> final manual-review recommendation
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

The model distinguishes no applications, single application, all rejected, no admitted applications, cancellation, contract-not-concluded, and unknown failure. Missing winner or price is not enough to infer zero applications.

### Recurring change feed

R4A reuses the existing SQLite state rather than introducing a parallel persistence model. Each saved run can emit `ChangeFeedEvent` records only for meaningful transitions.

Examples include:

- `NEW_PROCUREMENT`;
- deadline, NMCK, or status changes;
- preliminary/history score and decision changes;
- `PROCUREMENT_CLOSED`;
- `NEW_OPPORTUNITY`;
- `OPPORTUNITY_UPDATED`;
- `OPPORTUNITY_NO_LONGER_ACTIVE`.

Events preserve previous/current values and an explanation where applicable. Repeated identical runs are idempotent: an unchanged second run should emit no change-feed noise.

### Enrichment

`radar.enrichment`, `radar.live_collection`, `radar.artifact_registry`, and `radar.deep_assessment` download bounded sets of procurement documents for selected candidates and run the document analyzer.

### State and resilience

`radar.state` stores run/state data in SQLite. Existing procurement, assessment, opportunity, transition, and change tables are reused for recurring monitoring.

`radar.source_resolution` provides bounded recovery when EIS URLs are stale or intermittently unavailable.

### Reporting

`radar.reporting` writes structured reports and supports transactional publication. R4A adds the change feed to runtime JSON/CSV outputs and to the normal XLSX/Markdown reporting surfaces.

## Configuration

Primary examples:

- `config/radar.example.yaml`
- `config/search_profiles.yaml`

Important configuration areas include discovery, scoring, enrichment, historical intelligence, resilience, and opportunity/failure-history limits.

## Core CLI

```powershell
.\.venv\Scripts\python.exe -m radar.runner --help
```

Use the CLI help as the final source of truth for current flags.

## Decision philosophy

The Radar separates evidence layers deliberately:

- a technically attractive procurement can still have poor historical economics;
- missing historical data is not a rejection signal;
- historical failure is not automatically a positive signal;
- zero applications is different from cancellation or all applications being rejected;
- a failed historical procedure is not itself a current opportunity;
- a current procurement must still be open and technically eligible;
- recurring monitoring should surface meaningful changes rather than repeat unchanged cards;
- partial protocol evidence contributes only to the metric it supports;
- low-confidence metrics remain low-confidence in the final report.

## Validation status

R3B.1 validated the live failed-history path against real EIS data and confirmed two real `SINGLE_APPLICATION` events from protocol pages.

R4A was accepted with `151 passed`. A two-run validation using one SQLite database produced 12 `NEW_PROCUREMENT` events on the baseline run and zero new/changed/change-feed events on the identical second run.

## Safety and repository hygiene

Real procurement documents, live HTML, SQLite state, generated reports, browser state, and downloaded protocol artifacts are runtime data and must remain outside Git.

See also:

- [Live discovery](RADAR_LIVE_DISCOVERY.md)
- [Enrichment](RADAR_ENRICHMENT.md)
- [Historical intelligence](RADAR_HISTORICAL_INTELLIGENCE.md)
- [Resilience](RADAR_RESILIENCE.md)
- [Analog selection](RADAR_ANALOG_SELECTION.md)
- [Result extraction](RADAR_RESULT_EXTRACTION.md)
- [Opportunity intelligence](RADAR_OPPORTUNITIES.md)
- [Recurring change feed](RADAR_CHANGE_FEED.md)
