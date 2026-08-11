# R4C Notification-ready Alert Filtering

R4C converts the full recurring `change_feed` into a smaller, deterministic `alert_feed` intended for outbound delivery.

Current Radar version: `0.4.6-r4f1-state-guardrails`.

## Purpose

The change feed is a technical record of meaningful state transitions. Not every change deserves an operator notification. `radar.alerts` applies explicit rules and configured thresholds so downstream delivery channels receive only higher-value events.

## Alert model

Each `AlertFeedItem` preserves procurement number, alert type, alert priority (`HIGH`, `MEDIUM`, `LOW`), detection time, reason/explanation, source event types and field names, previous/current values, source change events, current score/decision when available, and a deterministic fingerprint.

## Promotion rules

The deterministic rules can promote `NEW_OPPORTUNITY`, interesting new procurements, transitions into `PRIORITY`, significant opportunity improvements, significant NMCK changes, urgent deadlines, and explicit `PROCUREMENT_CLOSED` / `OPPORTUNITY_NO_LONGER_ACTIVE` events for interesting items.

Changes that do not meet an alert rule are suppressed rather than forwarded automatically.

## Closure/inactivity evidence guardrail

R4F.1 hardens the source-event contract used by the alert layer.

A procurement being absent from a bounded recurring run does **not** create `PROCUREMENT_CLOSED`. An opportunity being absent does **not** create `OPPORTUNITY_NO_LONGER_ACTIVE`.

Those events require explicit state evidence upstream. As a result, absence-only cases cannot be promoted into closure/deactivation alerts and cannot reach Telegram.

The alert layer itself remains deterministic and does not infer closure from missing observations.

## Configuration

`config/radar.example.yaml` contains the `alerts` block with thresholds for interesting new procurements, high priority, significant opportunity-score increase, NMCK percentage change, and urgent deadlines. These values are policy thresholds, not learned parameters.

## Deduplication and idempotency

Several raw change events for one procurement can qualify during the same run. R4C groups them by procurement number and produces one concise alert where practical, preserving source evidence.

Alert fingerprints are persisted in SQLite `alert_history`. Repeated identical alerts are not re-emitted.

## Reporting

The filtered feed is exposed through `alert_feed.json`, `alert_feed.csv`, the XLSX `Alert Feed` sheet, Markdown reporting, and runtime summary fields.

These are runtime artifacts and should remain outside the repository.

## Validation

R4C was accepted with `161 passed`.

R4F.1 was accepted with `183 passed` and adds regression coverage proving that omission from a bounded run creates no closure/inactivity event, no alert, and no Telegram delivery, while explicit observed closure/inactivity remains supported.
