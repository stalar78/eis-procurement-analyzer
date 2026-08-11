# Documentation

This directory contains the public technical documentation for EIS Procurement Analyzer and EIS Procurement Radar.

## Core analyzer documentation

- [Architecture](ARCHITECTURE.md) — pipeline stages, module boundaries, source-dependent behavior, and reusable analytical concepts.
- [Methodology](METHODOLOGY.md) — document statuses, classification, strict extraction, evidence, conflicts, and decision layers.
- [Outputs](OUTPUTS.md) — generated reports, evidence and quality files, decision fields, and publication rules.

## Radar documentation

- [Radar overview](RADAR.md) — stateful live decision-support pipeline and decision layers.
- [Live discovery](RADAR_LIVE_DISCOVERY.md) — active-procedure search, status normalization, deadline checks, and detail verification.
- [Document enrichment](RADAR_ENRICHMENT.md) — controlled live collection, artifact validation, caching, and deep assessment.
- [Historical intelligence](RADAR_HISTORICAL_INTELLIGENCE.md) — completed-procurement analogs, competition metrics, confidence, and historical score adjustment.
- [Resilience and recovery](RADAR_RESILIENCE.md) — source recovery, last-known-good cache, bounded retries, and transactional publication.
- [Analog selection](RADAR_ANALOG_SELECTION.md) — source-aware queries, Russian normalization, category gating, and explainable similarity.
- [Historical result extraction](RADAR_RESULT_EXTRACTION.md) — 44-FZ/223-FZ result resolution, protocol parsing, multi-document assembly, and partial metric samples.
- [R3B opportunity intelligence](RADAR_OPPORTUNITIES.md) — failed-procurement evidence, republication matching, opportunity scoring, safeguards, and live-validation status.
- [R4A recurring change feed](RADAR_CHANGE_FEED.md) — persisted run comparison, meaningful transitions, idempotency, and change-feed reporting.

## Source of truth

Implementation and regression tests are the final source of truth for current behavior. Important code surfaces include:

- `collect_results.py`
- `score_results.py`
- `collect_candidate_details.py`
- `analyze_candidate_documents.py`
- `radar/`
- `tests/test_radar_*.py`
- `tests/test_strict_extraction.py`

Documentation explains the architecture and public contract but must not be used to claim a feature that is absent from code.

## Public-data rule

Do not place downloaded procurement documents, live page snapshots, generated analysis outputs, local datasets, SQLite state, browser storage, screenshots with personal data, cookies, tokens, secrets, or machine-specific paths in this directory.

Use only synthetic/test-oriented fixtures and fictional examples for public demonstrations.
