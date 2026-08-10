# EIS Procurement Radar

## Purpose

EIS Procurement Radar is the stateful decision-support layer of EIS Procurement Analyzer. It turns live EIS search results into a bounded, explainable pipeline for identifying procurements worth manual review.

Current Radar version: `0.3.4-r3a-result-extraction`.

The Radar is intentionally conservative. It does not bid, submit applications, predict a winning price, or replace legal/commercial review.

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

### Enrichment

`radar.enrichment`, `radar.live_collection`, `radar.artifact_registry`, and `radar.deep_assessment` download bounded sets of procurement documents for selected candidates and run the document analyzer.

### State and resilience

`radar.state` stores run/state data in SQLite. `radar.source_resolution` provides bounded recovery when EIS URLs are stale or intermittently unavailable.

### Reporting

`radar.reporting` writes structured reports and supports transactional publication. The latest attempted run and the latest publishable run can be represented separately.

## Configuration

Primary examples:

- `config/radar.example.yaml`
- `config/search_profiles.yaml`

Important configuration areas:

- discovery mode and budgets;
- status filters and date windows;
- scoring thresholds;
- enrichment limits;
- historical lookback/search limits;
- analog similarity;
- dumping thresholds;
- cache refresh windows.

## Core CLI

```powershell
.\.venv\Scripts\python.exe -m radar.runner --help
```

Typical controlled live discovery:

```powershell
.\.venv\Scripts\python.exe -m radar.runner `
  --profile medium_complexity_web `
  --discovery-mode ACTIVE_ONLY `
  --verify-open-from-detail `
  --limit 100 `
  --max-pages 2 `
  --output outputs\radar_active `
  --db data\radar_active.db `
  --verbose
```

## Decision philosophy

The Radar separates evidence layers deliberately:

- a technically attractive procurement can still have poor historical economics;
- missing historical data is not a rejection signal;
- a high-competition history does not automatically reject a strategically valuable procurement;
- partial protocol evidence can contribute only to the metric it supports;
- low-confidence metrics remain low-confidence in the final report.

## Safety and repository hygiene

Real procurement documents, live HTML, SQLite state, generated reports, browser state, and downloaded protocol artifacts are runtime data and must remain outside Git.

See also:

- [Live discovery](RADAR_LIVE_DISCOVERY.md)
- [Enrichment](RADAR_ENRICHMENT.md)
- [Historical intelligence](RADAR_HISTORICAL_INTELLIGENCE.md)
- [Resilience](RADAR_RESILIENCE.md)
- [Analog selection](RADAR_ANALOG_SELECTION.md)
- [Result extraction](RADAR_RESULT_EXTRACTION.md)
