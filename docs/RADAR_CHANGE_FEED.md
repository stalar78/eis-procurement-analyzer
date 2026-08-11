# R4A Recurring Change Feed

R4A turns persisted Radar runs into a concise change stream instead of forcing every run to be reviewed from scratch.

Current Radar version: `0.4.0-r4a-change-feed`.

## Purpose

The change feed compares the current run with previously persisted SQLite state and emits only meaningful transitions.

It is designed for recurring monitoring, where the operational question is not only “what procurements exist?” but also “what changed since the last run?”.

## Event model

`ChangeFeedEvent` stores:

- procurement number;
- event type;
- detection time;
- field name;
- previous value;
- current value;
- severity;
- source;
- explanation.

Current event classes include:

- `NEW_PROCUREMENT`;
- `DEADLINE_CHANGED`;
- `NMCK_CHANGED`;
- `STATUS_CHANGED`;
- preliminary score/decision changes;
- history-adjusted score/decision changes;
- `PROCUREMENT_CLOSED`;
- `NEW_OPPORTUNITY`;
- `OPPORTUNITY_UPDATED`;
- `OPPORTUNITY_NO_LONGER_ACTIVE`.

## Persistence

R4A reuses the existing SQLite model, including procurement state, assessments, opportunity assessments, opportunity transitions, and the existing `changes` table. No parallel change-feed database was introduced.

The comparison layer reads the previous state before saving the new state, emits transitions where values differ, and then persists the new current snapshot.

## Idempotency

Repeated identical runs should not generate repeated events.

The R4A validation used one local SQLite database across two fixture runs:

1. baseline run: 12 new procurements and 12 `NEW_PROCUREMENT` events;
2. identical second run: 0 new procurements, 0 changed procurements, and 0 change-feed events.

This is the key operational guarantee for later scheduled monitoring.

## Reporting

The change feed is included in structured runtime reporting. Current surfaces include:

- `change_feed.json`;
- `change_feed.csv`;
- the normal XLSX report;
- the normal Markdown report.

Generated runtime outputs remain local and are not committed to the repository.

## Boundaries

R4A does not yet schedule recurring runs and does not send notifications. It only provides the reliable persisted comparison layer needed by those later features.

A procurement disappearing from the current run is interpreted through persisted state and explicit change logic; recurring orchestration must still ensure comparable run scope so that collection failures are not mistaken for meaningful business changes.

## Validation

R4A code acceptance completed with `151 passed` and `git diff --check` clean.

The next operational step is recurring orchestration with run locking, lifecycle control, retention, and failure isolation before notification channels are added.
