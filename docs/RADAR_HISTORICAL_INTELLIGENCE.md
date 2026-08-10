# Radar Historical Intelligence

## Goal

Historical intelligence estimates whether a currently interesting procurement belongs to a market with low, moderate, high, or extreme competition.

It is not a winning-price predictor. The layer produces explainable historical evidence, sample sizes, and confidence levels.

## Flow

```text
live candidate
    -> source-aware historical queries
    -> completed procurement discovery
    -> candidate deduplication
    -> category compatibility
    -> explainable similarity scoring
    -> bounded analog selection
    -> result/protocol resolution
    -> field-level result assembly
    -> competition metrics
    -> dumping-risk assessment
    -> history-adjusted assessment
```

## Historical queries

Queries are generated from source evidence rather than from the whole Radar profile indiscriminately. High-value source phrases and category signals are preferred; broad profile terms are fallback signals.

This avoids cases where a portal procurement is searched using unrelated terms merely because those terms exist elsewhere in the same profile.

## Similarity

Analog similarity is deterministic and decomposable. Depending on available fields it can use:

- functional-term overlap;
- title overlap;
- profile/category compatibility;
- customer match;
- procedure type;
- NMCK band;
- region.

Category gating rejects obvious mismatches before relaxed similarity thresholds are considered.

Selected analogs can be marked as normal, relaxed-threshold, or same-customer fallback selections. Relaxation is explicit rather than hidden.

## Result evidence

Selected analogs are resolved through public EIS result/protocol paths. 44-FZ and 223-FZ are handled separately because their navigation and result layouts differ.

The result layer can assemble fields from multiple sources belonging to the same procurement:

- NMCK;
- final price;
- participant count;
- admitted participant count;
- winner;
- calculated reduction.

Every accepted field retains provenance and confidence.

## Partial usable evidence

An analog does not have to be completely populated to contribute useful evidence.

Examples:

- a valid participant count can contribute to participant metrics even if final price is unavailable;
- a valid NMCK/final-price pair can contribute to reduction metrics even if participant count is missing;
- winner evidence has its own sample size.

This prevents one unavailable field from discarding all other verified evidence.

## Competition metrics

Metrics can include:

- participant sample size;
- median/average participants;
- participant quartiles and maximum;
- reduction sample size;
- median/average reduction;
- reduction quartiles and maximum;
- high/extreme/severe reduction rates;
- no-application and all-rejected rates;
- winner sample size and repeat-winner signal;
- strong analog count;
- result completeness and warnings.

Medians are preferred as primary descriptive indicators where appropriate.

## Historical confidence

Confidence depends on the quantity and quality of usable evidence, including:

- sample size;
- strength of analog similarity;
- result completeness;
- consistency of the observed metrics;
- field-specific evidence availability.

A small sample should remain `LOW` or `INSUFFICIENT`; the system should not create false certainty.

## Dumping risk

The dumping-risk layer combines observed competition evidence into an explainable risk signal. Configurable thresholds distinguish normal competition from high, extreme, and severe price reductions.

The risk score is not a probability and should not be read as an expected winning-price percentage.

## History-adjusted assessment

Historical intelligence may adjust the preliminary score before document enrichment.

Important rules:

- high/extreme competition can lower priority;
- low competition may provide a small positive adjustment;
- missing history does not automatically mean `REJECT`;
- a technical hard reject cannot be reversed solely by favorable history;
- the original preliminary assessment remains stored.

## Customer and supplier context

The codebase also contains bounded customer-history and lightweight supplier-history support. These are public-procurement context signals, not legal or ethical judgments about organizations.

## Current milestone

At the R3A.4 milestone the live pipeline demonstrated non-empty result extraction from a bounded real analog set and produced independent participant and reduction samples. Confidence remained low in that trial, which is expected behavior for a small sample.

The historical layer is therefore suitable for controlled recurring use, provided confidence and evidence coverage are reviewed manually.
