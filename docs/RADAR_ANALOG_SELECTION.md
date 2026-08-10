# Radar Analog Selection

## Purpose

Historical intelligence depends on selecting comparable procurements without admitting unrelated records simply to increase sample size.

The analog-selection layer is rule-based, explainable, and source-aware.

## Why source-aware queries matter

Early live calibration showed that generic profile terms such as `личный кабинет` and `реестр` could dominate query generation even when they were not actually supported by the source procurement. This produced candidates that were searchable but not necessarily comparable.

R3A.3 changed the model so historical queries are driven first by the source procurement itself.

## Russian text normalization

`radar.analog_search` normalizes Russian procurement text before feature comparison. The implementation handles common encoding/mojibake issues, case, punctuation, whitespace, and selected term variants/synonym groups.

Terms are treated according to importance. Specific functional phrases should contribute more than generic procurement boilerplate.

Examples of higher-value concepts include:

- personal accounts;
- registries;
- application-processing workflows;
- administrative panels;
- information/investment portals;
- integrations and APIs;
- migration;
- document generation.

Broad terms such as `разработка`, `создание`, or generic service wording should not dominate similarity on their own.

## Category compatibility

Selection is effectively two-stage.

First, candidates are classified for category compatibility. Obvious category mismatches can be rejected before detailed scoring.

Then compatible candidates receive a weighted similarity score.

This is important because simply lowering a numerical threshold without category gating would allow hardware, licenses, or unrelated services into a web/software analog set.

## Similarity components

The scoring model can use explicit components such as:

- functional similarity;
- title similarity;
- profile/category similarity;
- customer similarity;
- procedure-type similarity;
- budget similarity;
- region similarity.

The final record preserves component scores and reasons rather than exposing only one opaque number.

## Selection modes

Selected analogs can identify how they qualified:

- normal threshold;
- relaxed threshold;
- same-customer fallback.

Relaxation is bounded and must not bypass a hard minimum floor or category mismatch.

## Query effectiveness

Historical query diagnostics can evaluate each query by candidate count and similarity distribution. This makes it possible to see whether a query is generating useful analogs or merely broad noise.

## Calibration principle

Thresholds should be calibrated against real candidate distributions, not lowered until a desired sample size appears.

Zero selected analogs is safer than a fabricated market sample. When no defensible analogs exist, the correct output is insufficient historical evidence.
