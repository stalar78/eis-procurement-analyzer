# R4C Notification-ready Alert Filtering

R4C converts the full recurring `change_feed` into a smaller, deterministic `alert_feed` intended for future outbound delivery.

Current Radar version: `0.4.2-r4c-alert-filtering`.

## Purpose

The change feed is a technical record of meaningful state transitions. Not every change deserves an operator notification. `radar.alerts` applies explicit rules and configured thresholds so downstream delivery channels receive only higher-value events.

No Telegram, email, webhook, or other sender is implemented in this stage. R4C decides what is important; a later delivery adapter should only transport the resulting alert payload.

## Alert model

Each `AlertFeedItem` preserves:

- procurement number;
- alert type;
- alert priority (`HIGH`, `MEDIUM`, `LOW`);
- detection time;
- reason/explanation;
- source event types and field names;
- previous/current values;
- source change events;
- current score and Radar decision when available;
- deterministic fingerprint.

## Promotion rules

The current deterministic rules can promote:

- `NEW_OPPORTUNITY`;
- a new procurement whose decision is `PRIORITY` or `REVIEW`, or whose score exceeds the configured minimum;
- a preliminary/history decision transition into `PRIORITY`;
- an opportunity update whose score rises by at least the configured delta or whose opportunity level improves;
- an NMCK change whose absolute percentage change exceeds the configured threshold;
- a deadline change that moves the procurement into the configured urgent window;
- `PROCUREMENT_CLOSED` or `OPPORTUNITY_NO_LONGER_ACTIVE` when the item was previously interesting.

Changes that do not meet an alert rule are suppressed rather than forwarded automatically.

## Configuration

`config/radar.example.yaml` contains the `alerts` block:

```yaml
alerts:
  enabled: true
  minimum_new_score: 55
  high_priority_score: 75
  significant_opportunity_score_increase: 15
  significant_nmck_change_percent: 20
  urgent_deadline_days: 3
```

These values are policy thresholds, not learned parameters.

## Deduplication

Several raw change events for one procurement can qualify during the same run. R4C groups them by procurement number and produces one concise alert where practical.

The highest alert priority wins. Source events, event types, field names, and explanations are retained so the merged alert remains explainable.

## Idempotency

Alert fingerprints are persisted in SQLite `alert_history`.

Before publishing the final alert feed, already-recorded fingerprints are filtered out. A repeated identical run therefore does not re-emit the same alert solely because the underlying procurement remains present.

This is separate from R4A change-feed idempotency: R4A suppresses unchanged state transitions; R4C additionally prevents duplicate alert emission.

## Reporting

R4C exposes `alert_feed` through the existing runtime reporting layer:

- `alert_feed.json`;
- `alert_feed.csv`;
- XLSX `Alert Feed` sheet;
- Markdown alert section;
- alert count/feed fields in summary/JSON reporting.

These are runtime artifacts and should remain outside the repository.

## Validation

R4C was accepted with `161 passed` in the full local test suite.

Deterministic tests cover:

- promotion of an important event;
- suppression of low-value noise;
- transition into `PRIORITY`;
- urgent deadline detection;
- per-procurement deduplication;
- idempotent repeated alert processing.

`git diff --check` and `python -m compileall radar` also completed successfully at the milestone.

## Next boundary

The next delivery stage should consume the already-filtered `alert_feed` without reimplementing Radar scoring or alert-selection rules inside Telegram, email, or another transport.
