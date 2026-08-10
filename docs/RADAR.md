# EIS Procurement Radar

## Purpose

EIS Procurement Radar is the stateful decision-support layer of EIS Procurement Analyzer. It turns live EIS search results into a bounded, explainable pipeline for identifying procurements worth manual review.

Current Radar version: `0.3.5-r3b-opportunities`.

The Radar is intentionally conservative. It does not submit applications or replace legal/commercial review.

## End-to-end flow

```text
active EIS discovery
    -> deduplication and state
    -> provisional eligibility/scoring
    -> detail-page open verification
    -> historical analog search
    -> category compatibility + similarity scoring
    -> historical result/protocol extraction
    -> competition metrics + confidence
    -> history-adjusted assessment
    -> failed-procurement / republication opportunity intelligence
    -> controlled document enrichment
    -> deep assessment
    -> final manual-review recommendation
```

## Main layers

### Discovery

`radar.discovery`, `radar.search_request`, `radar.search_profiles`, and `radar.open_verification` discover candidate procurements and distinguish currently open procedures from completed, cancelled, unknown, or conflicting states.

The default live mode is `ACTIVE_ONLY`.

### Preliminary scoring

`radar.prefilter` and `radar.scoring` apply configurable rule-based filters and scores. Technical interest, budget, deadline, complexity, data quality, commodity risk, and negative platform/security signals are handled separately.

Decisions include `PRIORITY`, `REVIEW`, `WATCH`, `REJECT`, and `INSUFFICIENT_DATA`.

### Historical intelligence

`radar.historical`, `radar.analog_search`, `radar.competition_metrics`, and `radar.result_extraction` search completed procurements, select explainable analogs, resolve result/protocol evidence, and calculate competition metrics.

Historical evidence adjusts but does not overwrite the preliminary assessment.

### Failed-procurement opportunities

`radar.opportunities` adds a separate opportunity-intelligence layer for evidence-backed historical failures and likely republications.

It distinguishes cases such as `NO_APPLICATIONS`, `SINGLE_APPLICATION`, `ALL_APPLICATIONS_REJECTED`, `NO_ADMITTED_APPLICATIONS`, cancellation, contract-not-concluded, and unknown failure. Missing winner or price is not enough to infer zero applications.

The layer links a failed historical procurement to a later current procurement using explainable relation components such as customer, functional/title similarity, budget, procedure, region, temporal proximity, and explicit references.

A separate opportunity score can promote manual review when a current procurement is verified open, technically suitable, and related to weak historical competition. Technical hard rejects and closed/unverified procedures cannot become high-priority opportunities solely because of a historical failure.

### Enrichment

`radar.enrichment`, `radar.live_collection`, `radar.artifact_registry`, and `radar.deep_assessment` download bounded sets of procurement documents for selected candidates and run the document analyzer.

### State and resilience

`radar.state` stores run/state data in SQLite. `radar.source_resolution` provides bounded recovery when EIS URLs are stale or intermittently unavailable.

R3B also persists failure events, republication links, opportunity assessments, and opportunity transitions for reuse across runs.

### Reporting

`radar.reporting` writes structured reports and supports transactional publication. The latest attempted run and the latest publishable run can be represented separately.

## Configuration

Primary examples:

- `config/radar.example.yaml`
- `config/search_profiles.yaml`

Important configuration areas now include discovery, scoring, enrichment, historical intelligence, resilience, and an `opportunities` section for failure-history limits, republication windows/scores, and opportunity thresholds.

## Core CLI

```powershell
.\.venv\Scripts\python.exe -m radar.runner --help
```

R3B adds opportunity-related CLI controls including failed-opportunity enable/disable flags, failure-history-only mode, bounded failure query/page/candidate limits, republication-link limits, minimum opportunity score, and failure-history refresh.

## Decision philosophy

The Radar separates evidence layers deliberately:

- a technically attractive procurement can still have poor historical economics;
- missing historical data is not a rejection signal;
- historical failure is not automatically a positive signal;
- zero applications is different from cancellation or all applications being rejected;
- a failed historical procedure is not itself a current opportunity;
- a current procurement must still be open and technically eligible;
- partial protocol evidence can contribute only to the metric it supports;
- low-confidence metrics remain low-confidence in the final report.

## Validation status

R3B code acceptance completed with `142 passed` in the full local test suite.

Synthetic fixtures cover explicit no-application cases, single application, all rejected, cancellation, relation scoring, temporal ordering, explicit republication references, closed current procedures, and technical hard rejects.

The first bounded live R3B validation returned zero unique current cards. Therefore the opportunity layer is code/offline-accepted but still requires controlled live failure-discovery validation before it is treated as proven on a real open EIS procurement.

## Safety and repository hygiene

Real procurement documents, live HTML, SQLite state, generated reports, browser state, and downloaded protocol artifacts are runtime data and must remain outside Git.

See also:

- [Live discovery](RADAR_LIVE_DISCOVERY.md)
- [Enrichment](RADAR_ENRICHMENT.md)
- [Historical intelligence](RADAR_HISTORICAL_INTELLIGENCE.md)
- [Resilience](RADAR_RESILIENCE.md)
- [Analog selection](RADAR_ANALOG_SELECTION.md)
- [Result extraction](RADAR_RESULT_EXTRACTION.md)
