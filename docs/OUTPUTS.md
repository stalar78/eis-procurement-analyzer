# Outputs

## General rule

All real analysis outputs are local generated data. They may contain procurement identifiers, customer names, document text, prices, links, protocol material, and other public-source data that should not be committed to the public repository.

Only synthetic/test-oriented fixtures and examples belong in Git.

## Original analyzer outputs

The document analyzer can produce consolidated XLSX/JSON/CSV/Markdown reports plus extraction/classification/evidence artifacts.

Typical analyzer artifacts include:

- `procurement_analysis.xlsx`
- `procurement_analysis.json`
- `procurement_analysis.csv`
- `analysis_summary.md`
- `extraction_manifest.csv`
- `document_classification.csv`
- `evidence_index.csv`
- `unresolved_fields.csv`
- `quality_issues.csv`
- `field_conflicts.csv`
- `rejected_candidates.csv`

The exact sheet/file set depends on the current writer implementation and available evidence.

## Radar run outputs

Radar writes local structured outputs under the configured output directory. Depending on the selected modes, a run may contain:

- `latest.json`
- `latest.md`
- `latest.xlsx`
- `latest_attempt.json`
- per-run directories under `runs/`
- failed/blocked attempt directories where configured
- discovery diagnostics
- status audit
- open-verification records
- enrichment plans and diagnostics
- historical query plans
- historical candidates and analog selections
- result/protocol extraction diagnostics
- competition metric evidence and samples

Generated summary records include the application `radar_version` and the short Git `build_identity` when repository metadata is available, allowing a local run artifact to be associated with the code revision that produced it.

## Transactional publication

Real Radar runs are published transactionally.

A run is first written as a run-specific attempt. According to its quality state, it can then become the latest publishable result.

`latest_attempt.json` can advance even when a blocked or failed attempt must not replace the previous useful `latest.*` output.

This distinction protects useful reports from unstable external EIS responses.

## Discovery outputs

Discovery reporting can include:

- search diagnostics;
- status distributions;
- filter fingerprints;
- provisional-open counts;
- detail-page verification results;
- structured detail-unavailable failure-code counts/examples;
- detail source strategy and resolution status;
- redacted detail source/recovered/last-known-good identifiers where applicable;
- proven-canonical retry attempted/count/outcome/failure-code/HTTP-status fields where applicable;
- recent-proven-source and degraded absence-certainty fields where applicable;
- deadline/status conflicts;
- query/page/card budget usage.

R4H keeps source diagnostics evidence-oriented. Public diagnostic rows may show safe structured states such as `PROVEN_CANONICAL_RETRY`, `PROVEN_SOURCE_TEMPORARILY_UNAVAILABLE`, and `DEGRADED_BY_RECENT_PROOF`, but they must not expose raw exception text, raw HTML, credentials, or unredacted sensitive source identifiers.

These files are operational diagnostics, not public examples.

## Enrichment outputs

Controlled enrichment can produce:

- enrichment plan;
- artifact manifest/registry data;
- per-procurement downloaded documents;
- extracted/analyzed material;
- deep assessments;
- preliminary-to-final decision transitions;
- download and analyzer diagnostics.

Downloaded documents and analysis directories are intentionally ignored by Git.

## Historical intelligence outputs

Historical analysis can produce:

- historical query plan;
- raw/unique/scored historical candidates;
- selected analogs;
- analog score diagnostics;
- query-effectiveness diagnostics;
- customer/supplier history summaries;
- repeated-procurement links;
- competition metrics;
- dumping-risk assessment;
- history-adjusted assessment.

Historical output must preserve evidence and confidence rather than presenting an unsupported prediction.

## Historical result extraction outputs

Result-extraction runs may include:

- `analog_result_resolution.json`
- `analog_result_resolution.csv`
- `protocol_extraction_diagnostics.json`
- `assembled_historical_results.json`
- `competition_metric_samples.json`

These files explain how selected analogs were resolved and which fields contributed to each competition metric.

## Separate metric samples

The historical layer tracks independent evidence samples where possible:

- participant sample size;
- reduction sample size;
- winner sample size;
- complete-result sample size.

A partially populated analog can therefore contribute to one supported metric without being treated as complete for all metrics.

## Evidence and quality principle

Missing or unresolved values are expected. They must not be replaced with guesses.

Important values should remain traceable to accepted source evidence, with conflicts, partial extraction, and unavailable documents reported explicitly.

Recent stored source evidence may reduce confidence in a same-run absence conclusion, but it never substitutes for a current live verification. In particular, `PROVEN_SOURCE_TEMPORARILY_UNAVAILABLE` remains a `DETAIL_UNAVAILABLE` outcome, not `VERIFIED_OPEN`.

## Decision fields

Depending on the stage, reports may expose:

- preliminary score/decision;
- open-verification status;
- historical confidence;
- analog count and strong-analog count;
- participant/reduction metrics;
- competition/dumping risk;
- history-adjusted score/decision;
- technical participation verdict;
- deep assessment;
- final manual-review recommendation;
- manual-review flags and warnings.

Previous decision layers are preserved rather than overwritten silently.

## Synthetic public examples

Public examples should use:

- invented procurement identifiers;
- fictional customers;
- invalid/example URLs;
- invented filenames and excerpts;
- values that do not reproduce a real procurement record.

## Development-run aggregate figures

The earlier audited local analyzer artifacts confirmed:

- 1,237 unique collected records;
- 15 selected candidates;
- 125 downloaded documents;
- at least one analyzed case requiring manual review because of an extreme price reduction.

Later Radar development validated historical analog/result extraction and R4H source-resilience behavior on bounded real public-source runs, but the real run artifacts themselves remain local and are not published in the repository.

Project claims should continue to distinguish capability demonstrations from statistically representative market conclusions.
