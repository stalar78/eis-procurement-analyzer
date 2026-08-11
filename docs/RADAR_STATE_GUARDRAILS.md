# R4F.1 State-transition Guardrails

R4F.1 corrects an important recurring-monitoring semantic: **absence from a bounded Radar run is not evidence of closure or inactivity**.

Current Radar version: `0.4.6-r4f1-state-guardrails`.

## Procurement closure

Previous behavior could emit `PROCUREMENT_CLOSED` when a procurement persisted in SQLite was simply missing from the next bounded run.

That inference is unsafe because discovery is intentionally bounded by queries, page limits, ordering, and transient EIS behavior.

R4F.1 removes absence-based closure inference. `PROCUREMENT_CLOSED` now requires an explicit observed status transition into a supported closed state such as:

- `closed`;
- `completed`;
- `cancelled`;
- `contract_signed` / contract-signed equivalent.

A procurement omitted from the latest bounded run remains previously observed state; no closure event is created solely from omission.

## Opportunity inactivity

The same defect existed in opportunity persistence: a previously stored opportunity could be marked `OPPORTUNITY_NO_LONGER_ACTIVE` because it was not present in the latest scoped result.

R4F.1 removes this absence-only transition. Opportunity inactivity must now be supplied as an explicit `OpportunityTransition` from supported opportunity logic.

## Downstream effects

Because the change feed no longer creates absence-only closure/inactivity events:

- `radar.alerts` receives no false closure/deactivation source event;
- the alert feed remains empty for absence-only cases;
- `radar.telegram_delivery` receives nothing to send;
- bounded-search variation cannot by itself generate a production notification.

## Preserved behavior

The guardrail does not suppress real state transitions.

Explicit observed procurement closure still emits `PROCUREMENT_CLOSED`.

Explicit opportunity inactivity still emits `OPPORTUNITY_NO_LONGER_ACTIVE`.

## Validation

R4F.1 was accepted with `183 passed`.

Regression tests cover:

- persisted open procurement omitted from a later run -> no closure event;
- omitted opportunity -> no inactivity event;
- explicit closed procurement status -> closure event preserved;
- explicit opportunity inactivity transition -> event preserved;
- absence-only case -> no alert;
- absence-only case -> no Telegram HTTP delivery attempt.

## Operational significance

This milestone is a production notification guardrail. It should be in place before Telegram is enabled for live recurring runs or before Windows Task Scheduler is activated for unattended monitoring.
