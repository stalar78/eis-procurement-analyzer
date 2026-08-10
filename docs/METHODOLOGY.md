# Methodology

## Purpose

The project is built around a conservative rule:

> A missing value is preferable to a confident-looking value that cannot be supported by an allowed source.

That rule applies both to the original document analyzer and to EIS Procurement Radar. Extraction, validation, evidence, confidence, and decision support remain separate layers.

## 1. Document status

The analyzer distinguishes several situations that must not be collapsed into one value:

- `read` — the relevant document was found and successfully parsed;
- `partial` — only part of the content could be extracted;
- `unreadable` — the document exists but could not be read reliably;
- `missing` — no acceptable document of the required type was found.

An unreadable contract is not evidence that no contract exists.

## 2. Document classification

Classification uses filename, card section, extracted text, stable phrases, and score-based rules.

Typical classes include technical specifications, technical attachments, contract drafts, signed contracts, NMCK calculations, application requirements, information cards, clarifications, protocols, notices, signatures, and other files.

Classification controls which documents are allowed to support particular fields.

## 3. Allowed-source extraction

Important values are not accepted from arbitrary text matches.

| Field | Preferred or allowed source |
|---|---|
| Initial maximum contract price | NMCK calculation, procurement card, or notice |
| Final contract price | Final protocol, supported structured result, or signed/concluded contract evidence |
| Participant count | Protocol or supported structured result |
| Functional scope | Technical specification and clarification |
| Participant requirements | Application requirements or information card |
| Acceptance and rights | Contract draft, signed contract, and technical specification |

The exact code rules remain the source of truth.

## 4. Strict financial extraction

Financial documents often contain unrelated amounts: guarantees, taxes, penalties, line-item values, reference prices, application identifiers, percentages, and formatting artifacts.

The strict extraction layer therefore:

1. checks the source/document class;
2. looks for context-specific patterns;
3. rejects unsupported candidates;
4. records accepted evidence;
5. records unresolved/rejected candidates separately;
6. detects contradictory accepted values instead of choosing silently.

Reduction is calculated only from a supported NMCK and supported final price when the relationship is valid.

## 5. Evidence model

An accepted field can be linked to evidence metadata containing:

- procurement identifier;
- field name and accepted value;
- source page/document;
- document/result class;
- page, sheet, row, cell, or text location where available;
- excerpt or structured source context;
- extraction method;
- confidence/reliability information.

Evidence makes manual verification possible. It is not a guarantee that the source is legally sufficient for every use.

## 6. Conflicts and unresolved values

When allowed sources disagree, the system can record a field conflict rather than selecting one value without disclosure.

When no acceptable evidence exists, the field remains unresolved.

Missing data should not be transformed into a negative business conclusion merely because it is missing.

## 7. Radar open-procedure methodology

For live participation screening, a procurement should not be considered open solely because of a keyword in the search card.

Radar separates:

- raw EIS status;
- normalized status;
- future/past application deadline;
- cancellation/completion signals;
- optional detail-page verification.

A status/deadline conflict blocks automatic promotion into the enrichment path unless explicitly forced for diagnostic purposes.

## 8. Historical analog methodology

Historical analogs are selected through explainable rule-based features rather than opaque semantic scoring.

The model considers source-aware functional/title terms, category compatibility, customer, procedure type, budget relationship, region, and profile/category evidence.

Category mismatches can reject candidates before relaxed thresholds are applied.

Threshold relaxation is explicit and bounded. The objective is not to force a minimum number of analogs.

## 9. Historical result methodology

Competition evidence may be distributed across several EIS result/protocol pages.

The result layer can assemble fields from multiple sources belonging to one procurement. Each field retains its own provenance.

A partial analog can remain useful:

- participant evidence can enter participant metrics without a final price;
- final-price evidence can enter reduction metrics without participant data;
- winner evidence has its own sample.

This avoids an all-or-nothing completeness rule.

## 10. Competition metrics

Where sufficient evidence exists, Radar can calculate:

- median/average participants;
- participant quartiles and maximum;
- median/average reduction;
- reduction quartiles and maximum;
- high/extreme/severe reduction rates;
- no-application and all-rejected rates;
- repeated-winner signal.

Medians are preferred as primary market descriptors when outliers are likely.

Each metric should retain its contributing sample and sample size.

## 11. Historical confidence

Historical confidence depends on evidence quantity and quality, not only on whether a numerical score exists.

Factors include:

- usable sample size;
- strong analog count;
- similarity quality;
- field completeness;
- protocol/result provenance;
- consistency of observed values.

A small sample should remain `LOW` or `INSUFFICIENT` even when a risk score can technically be calculated.

## 12. Dumping/competition risk

Large reductions are not automatically interpreted as wrongdoing. The model describes observed market competition and price reduction patterns.

Risk levels such as `LOW`, `MODERATE`, `HIGH`, `EXTREME`, or `UNKNOWN` are decision-support categories, not probabilities.

Historical competition should not be described as an exact winning-price forecast.

## 13. Separate decision layers

The project keeps different questions separate.

### Preliminary Radar assessment

Card-level eligibility and fit produce decisions such as:

- `PRIORITY`;
- `REVIEW`;
- `WATCH`;
- `REJECT`;
- `INSUFFICIENT_DATA`.

### Open verification

Checks whether the procedure is actually available for participation.

### Historical assessment

Evaluates comparable completed procurements and competition evidence.

### History-adjusted assessment

Applies a bounded historical adjustment while preserving the original preliminary score/decision. Insufficient historical data does not automatically create `REJECT`.

### Deep technical assessment

Document enrichment can produce technical verdicts such as:

- `TAKE_NOW`;
- `TAKE_WITH_CONDITIONS`;
- `TAKE_AFTER_PREPARATION`;
- `DO_NOT_TAKE`;
- `INSUFFICIENT_TECHNICAL_DATA`.

### Market/document result status

The analyzer separately tracks whether protocol/result data is complete, partial, unreadable, missing, conflicting, or requires manual review.

### Final recommendation

The final recommendation remains a manual-review priority, not an automated participation decision.

## 14. Price recommendations

The analyzer can calculate heuristic minimum/comfortable price fields from extracted scope and configured assumptions.

These are model estimates, not quotations, guarantees, or professional financial advice. Operational use still requires manual confirmation of labour, taxes, guarantees/security, infrastructure, support, legal terms, subcontracting, reserves, and organization-specific costs.

## 15. Resilience methodology

External EIS availability is treated as uncertain.

One failed URL is not definitive proof of absence when search recovery, alternate sections, or last-known-good cached evidence exist.

Cached evidence must be marked as cached/stale rather than presented as freshly retrieved.

Failed or externally blocked runs should not erase useful earlier published outputs.

## 16. AI and automation boundary

The current public implementation is deterministic and rule-based. It does not call external LLM APIs or use embeddings/ML for ranking.

Future AI-assisted explanations should remain subordinate to source evidence and deterministic validation for accepted facts and financial values.

## 17. Human responsibility

The system supports research, triage, and evidence organization.

It does not replace:

- legal review;
- financial review;
- technical estimation;
- verification of current procurement rules;
- examination of complete official documentation;
- the final decision to participate.
