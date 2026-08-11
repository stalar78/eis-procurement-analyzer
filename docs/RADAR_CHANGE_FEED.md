# R4A Recurring Change Feed

R4A turns persisted Radar runs into a concise change stream instead of forcing every run to be reviewed from scratch.

Current Radar version: `0.4.6-r4f1-state-guardrails`.

## Purpose

The change feed compares the current run with previously persisted SQLite state and emits only meaningful transitions.

It is designed for recurring monitoring, where the operational question is not only “what procurements exist?” but also “what changed since the last run?”.

## Event model

`ChangeFeedEvent` stores procurement number, event type, detection time, field name, previous/current values, severity, source, and explanation.

Current event classes include `NEW_PROCUREMENT`, deadline/NMCK/status changes, score/decision changes, `PROCUREMENT_CLOSED`, `NEW_OPPORTUNITY`, `OPPORTUNITY_UPDATED`, and `OPPORTUNITY_NO_LONGER_ACTIVE`.

## Evidence-based closure semantics

R4F.1 strengthens the original R4A transition contract.

A recurring Radar run is bounded: search queries, page budgets, result ordering, and transient EIS behavior can cause a previously observed procurement to be absent from a later run. **Absence alone is therefore not evidence that the procurement closed.**

The change feed no longer emits `PROCUREMENT_CLOSED` merely because a persisted procurement is not observed in the current bounded run. Closure requires an explicit observed status transition into a supported closed state such as `closed`, `completed`, `cancelled`, or a contract-signed equivalent.

The same rule applies to opportunity state. `OPPORTUNITY_NO_LONGER_ACTIVE` is not inferred from absence. It is emitted only when the opportunity layer supplies an explicit inactivity transition.

This guardrail matters downstream: absence-only cases produce no closure/inactivity event, no corresponding alert, and no Telegram delivery.

## Persistence

R4A reuses the existing SQLite model, including procurement state, assessments, opportunity assessments, opportunity transitions, and the existing `changes` table. No parallel change-feed database was introduced.

The comparison layer reads previous state before saving the new observation, emits supported transitions where values differ, and persists the new current snapshot.

## Idempotency

Repeated identical runs should not generate repeated events.

The original R4A validation used one local SQLite database across two fixture runs: a baseline run emitted new-procurement events, while an identical second run emitted no change-feed noise.

R4F.1 adds another idempotency/safety guarantee: omission from a later bounded run does not create a false closure or opportunity-deactivation transition.

## Reporting

The change feed is included in structured runtime reporting through `change_feed.json`, `change_feed.csv`, the normal XLSX report, and the normal Markdown report.

Generated runtime outputs remain local and are not committed to the repository.

## Validation

R4A code acceptance completed with `151 passed`.

The R4F.1 guardrail was accepted with `183 passed`. Regression coverage verifies absence-only procurement and opportunity cases, explicit observed closure/inactivity, alert suppression, and zero Telegram delivery for absence-only state.
