# Radar Resilience and Recovery

## Why this layer exists

EIS pages and canonical-looking URLs can be unstable. During controlled live validation the same procurement could be reachable through one path and unavailable through another. Radar therefore treats source resolution as an explicit bounded process rather than assuming one permanent URL.

## Source resolution

`radar.source_resolution` supports multiple strategies:

1. supplied URL validation;
2. last-known-good URL;
3. exact procurement-number EIS search recovery;
4. alternate-section recovery;
5. cached source snapshot fallback.

A single `404` is not enough to conclude that a procurement no longer exists.

## Resolution states

The source-resolution model distinguishes conditions such as:

- live resolution;
- search recovery;
- alternate-section recovery;
- cached resolution;
- partial resolution;
- temporary unavailability;
- confirmed not found;
- procurement-number mismatch;
- invalid source.

Confidence and warnings accompany the resolved source.

## Temporary vs permanent failures

Potentially temporary conditions include rate limiting, 5xx responses, TLS resets, browser timeouts, inconsistent 200/404 responses, and previously successful URLs becoming unavailable.

Permanent failure requires stronger evidence, such as an exact-number mismatch or bounded recovery strategies failing with evidence that the procurement is not present.

Retries are bounded; the system must not loop indefinitely.

## Last-known-good state

Radar preserves useful source information across runs. A later transient failure should not erase a previously successful source URL or snapshot.

Cached evidence is labelled with freshness information and is not presented as freshly retrieved live evidence.

## Result recovery

Historical analog result/protocol resolution follows the same principle. A temporarily unavailable result page does not automatically invalidate the analog if another public section or a valid cached artifact can supply the same evidence.

## Transactional report publication

Real runs are published transactionally.

Conceptually:

```text
run attempt
    -> temporary/per-run output
    -> quality classification
    -> publishable run directory
    -> optional update of latest.*
```

`latest.*` represents the latest publishable result according to run-quality rules, while `latest_attempt.json` can represent the most recent attempt even when it was blocked or failed.

This prevents an empty unstable rerun from destroying a useful previous report.

## Run quality

The historical validation flow distinguishes successful, partially successful, externally blocked, internally blocked, and failed outcomes.

Missing historical evidence must not silently become a negative business conclusion. If historical adjustment cannot be supported, it can remain unapplied while the preliminary assessment is preserved.

## Repository safety

Source snapshots, cached EIS pages, downloaded protocols, SQLite state, browser state, and generated reports are runtime artifacts and should remain ignored by Git.
