# Methodology

## Purpose

The analyzer is built around a conservative rule:

> A missing value is preferable to a confident-looking value that cannot be supported by an allowed source.

The system therefore separates extraction, validation, evidence, quality state, and decision support.

## 1. Document status

The analyzer distinguishes several situations that must not be collapsed into one value:

- `read` — the relevant document was found and successfully parsed;
- `partial` — only part of the content could be extracted;
- `unreadable` — the document exists but could not be read reliably;
- `missing` — no acceptable document of the required type was found.

This distinction is important. An unreadable contract is not evidence that no contract exists.

## 2. Document classification

Classification uses filename, card section, extracted text, stable phrases, and score-based rules.

Typical classes include:

- `technical_specification`;
- `technical_attachment`;
- `contract_draft`;
- `signed_contract`;
- `nmck_calculation`;
- `application_requirements`;
- `information_card`;
- `clarification`;
- `final_protocol`;
- `auction_protocol`;
- `notice`;
- `bank_details`;
- `signature`;
- `other`.

Classification controls which documents are allowed to support particular fields.

## 3. Allowed-source extraction

Important values are not accepted from arbitrary text matches.

Examples of source restrictions:

| Field | Preferred or allowed source |
|---|---|
| Initial maximum contract price | NMCK calculation, procurement card, or notice |
| Final contract price | Final protocol or signed contract |
| Participant count | Protocol |
| Functional scope | Technical specification and clarification |
| Participant requirements | Application requirements or information card |
| Acceptance and rights | Contract draft, signed contract, and technical specification |

The exact code rules remain the source of truth. This table explains the principle rather than replacing implementation details.

## 4. Strict financial extraction

Financial documents often contain many unrelated amounts: guarantees, taxes, penalties, line-item values, reference prices, and formatting artifacts.

The strict extraction layer therefore:

1. checks the document class;
2. looks for context-specific patterns;
3. rejects unsupported candidates;
4. records accepted evidence;
5. records unresolved or rejected candidates separately;
6. detects contradictory accepted values instead of choosing silently.

Regression tests cover cases where a small unrelated number must not replace a contract price.

## 5. Evidence model

An accepted field can be linked to an evidence record containing:

- procurement identifier;
- field name;
- accepted value;
- source file;
- source document class;
- page, sheet, cell, or text location where available;
- source excerpt;
- extraction method;
- confidence or reliability information.

Evidence is intended to make manual verification possible. It is not a guarantee that the source document itself is legally sufficient.

## 6. Conflicts and unresolved values

When allowed sources disagree, the analyzer can record a field conflict rather than selecting one value without disclosure.

When no acceptable evidence exists, the field remains unresolved.

Related outputs include:

- `field_conflicts.csv`;
- `unresolved_fields.csv`;
- `rejected_candidates.csv`;
- `quality_issues.csv`.

The audited development dataset did not confirm a current technical-specification/clarification conflict, so that result is not presented as a verified project metric.

## 7. Data completeness and reliability

The decision model considers whether critical document groups were found and read.

A high completeness score does not make a heuristic recommendation legally binding. It only indicates that more of the expected evidence was available to the model.

Reliability should fall when:

- critical documents are missing;
- files are unreadable or only partially extracted;
- important fields remain unresolved;
- sources conflict;
- market protocols are unavailable;
- an extreme price reduction needs manual review.

## 8. Separate decision layers

### Technical participation verdict

Describes whether the documented technical scope appears suitable under the current heuristic model.

Possible values include:

- `TAKE_NOW`;
- `TAKE_WITH_CONDITIONS`;
- `TAKE_AFTER_PREPARATION`;
- `DO_NOT_TAKE`;
- `INSUFFICIENT_TECHNICAL_DATA`.

### Market result status

Describes the availability and quality of market-result evidence.

Possible values include:

- `FULL_RESULT_AVAILABLE`;
- `PARTIAL_RESULT_AVAILABLE`;
- `PROTOCOL_NOT_AVAILABLE`;
- `PROTOCOL_UNREADABLE`;
- `EXTREME_REDUCTION_REVIEW_REQUIRED`;
- `RESULT_CONFLICT`.

### Overall recommendation

Combines available technical and market signals into a priority for manual review.

Possible values include:

- `PRIORITY_REVIEW`;
- `PROMISING`;
- `PROMISING_BUT_MARKET_UNKNOWN`;
- `PREPARE_FIRST`;
- `LOW_PRIORITY`;
- `REJECT`;
- `INSUFFICIENT_DATA`.

The exact gates are implemented in code and covered by regression tests.

## 9. Price recommendations

The analyzer can calculate heuristic minimum and comfortable price fields.

These values are model estimates based on extracted scope and configured assumptions. They are not quotations, guarantees, or professional financial advice.

Operational use requires manual confirmation of:

- labour estimate;
- taxes;
- guarantees and security;
- infrastructure;
- support obligations;
- legal terms;
- subcontracting;
- risk reserve;
- organization-specific costs.

## 10. Extreme reductions

Very large reductions are not automatically interpreted as violations or fraud.

The analyzer can mark them for manual review and exclude them from ordinary market aggregates where appropriate.

The audited local development artifacts confirm at least one case with a reduction above 90%, but real procurement details are not published in this repository.

## 11. AI and automation boundary

The current public implementation is deterministic and rule-based. It does not call external LLM APIs.

Future LLM-assisted summaries could be added only as a separate explanatory layer. Accepted facts and financial values should continue to depend on source evidence and deterministic validation.

## 12. Human responsibility

The analyzer supports research and preliminary triage.

It does not replace:

- legal review;
- financial review;
- technical estimation;
- verification of current procurement rules;
- examination of the complete official documentation;
- the final decision to participate.
