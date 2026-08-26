# Radar Resilience and Recovery

## Why this layer exists

EIS pages and canonical-looking URLs can be unstable. During controlled live validation the same procurement could be reachable through one path and unavailable through another. Radar therefore treats source resolution and recurring execution state as explicit bounded processes rather than assuming one permanent URL or one perfect run.

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

Potentially temporary conditions include rate limiting, 5xx responses, TLS resets, browser timeouts, inconsistent 200/404 responses, temporarily unavailable detail pages, and previously successful URLs becoming unavailable.

Permanent or rejecting conclusions require stronger evidence. For active discovery, explicit verified closure/cancellation or supported status/deadline conflicts remain negative evidence; temporary detail-page unavailability does not.

Retries are bounded; the system must not loop indefinitely.

## Detail-verification degradation

R4F.3 makes unavailable verification an explicit degradation state rather than a hidden rejection.

For a provisionally-open discovery candidate:

- `VERIFIED_OPEN` preserves the candidate;
- `DETAIL_UNAVAILABLE` preserves the candidate but does not upgrade it to verified-open;
- verification skipped because of the configured verification limit preserves the candidate;
- verified closed/cancelled outcomes reject the candidate;
- status/deadline conflicts retain conservative rejecting semantics.

This protects live discovery from transient EIS detail-page failures while preserving explicit negative evidence.

A controlled live validation observed 13 provisionally-open candidates whose detail pages were all temporarily unavailable. R4F.3 correctly retained all 13 candidates and recorded the unavailable-verification diagnostics.

## R4H source-resilience chain

R4H extends resilience from single-run degradation to cross-run source evidence.

### Structured failure diagnostics

R4H.1 records deterministic detail failure codes rather than collapsing every problem into one generic unavailable state. Diagnostics distinguish missing source URL, request/HTTP failure, identity mismatch, missing detail status/deadline, source recovery failure, confirmed source absence, and later R4H temporary-proven-source semantics. Public diagnostics do not expose raw exception text or raw HTML.

### Native Windows trust

R4H.2 routes Windows production Requests through native system certificate trust. This fixed a production condition where ordinary Python Requests rejected the EIS chain while Windows-native tooling accepted it. The implementation does not use `verify=False`, `CERT_NONE`, global certificate-disable monkeypatches, or suppressed warnings.

### Bounded source recovery

R4H.3 performs bounded recovery after a missing/stale direct detail URL. Direct source validation remains first; exact-number search and alternate-section logic are bounded and preserve 44-FZ / 223-FZ source-family safety.

R4H.4 hardens exact-search semantics. A recognized exact-search result page with no matching procurement link can produce `NOT_FOUND_CONFIRMED`; an unrecognized 200 response is treated as temporary/unrecognized evidence instead of absence.

### Last-known-good persistence

R4H.5 persists successful detail locators through the existing Radar SQLite state. A source becomes last-known-good only after a real live fetch contains the expected procurement identity and passes detail verification.

Remembered metadata is a locator, not a cached truth statement. Every reuse is a fresh live request and must pass the same verification rules before `VERIFIED_OPEN` can be produced.

The remembered source uses the existing freshness policy and does not introduce a second cache-age model.

### Proven canonical retry

R4H.6 recognizes the special case where the current direct source equals a recently proven last-known-good source. If the first live request fails with `404`, request error, `429`, or selected `5xx`, Radar performs exactly one additional same-URL live retry before continuing to the existing bounded resolver.

No extra same-URL retry is added for an unproven direct URL. A different remembered source keeps the existing `LAST_KNOWN_GOOD` path.

R4H.6.1 preserves safe structured retry metadata through later recovery or final failure, including whether retry was attempted, retry count, success/failure outcome, safe failure code, and HTTP status. This makes the complete production fallback chain observable even when a later resolver result becomes the final row.

### Recent-proof absence certainty

R4H.7 addresses a production-observed EIS behavior: a previously live-validated canonical URL can return repeated HTTP `404` responses, while a later resolver attempt in the same run may still recover the procurement live.

Therefore, when recent last-known-good evidence exists and the entire current live chain ultimately ends in `NOT_FOUND_CONFIRMED`, Radar does not immediately expose that as durable `SOURCE_URL_NOT_FOUND`. The final verification remains fail-closed as `DETAIL_UNAVAILABLE`, with:

- `detail_failure_code = PROVEN_SOURCE_TEMPORARILY_UNAVAILABLE`;
- `detail_recent_proven_source = true`;
- `detail_absence_certainty = DEGRADED_BY_RECENT_PROOF`.

This is not cache-based verification. The procurement is **not** marked `VERIFIED_OPEN` unless current live content succeeds. Recent proof only reduces confidence in an absence conclusion produced during an unstable run.

If no fresh proven source exists, the established `SOURCE_URL_NOT_FOUND` behavior remains unchanged.

## Last-known-good state

Radar preserves useful source information across runs. A later transient failure should not erase a previously successful source URL or snapshot.

Cached evidence is labelled with freshness information and is not presented as freshly retrieved live evidence.

## Recurring-run lock resilience

Recurring execution uses `radar.lock` to prevent overlapping stateful runs.

R4B introduced stale-lock recovery based on lock age. R4F.2 adds Windows PID-aware recovery for interrupted runs:

- if the recorded PID is confirmed alive, the existing run remains protected and the new run is locked out;
- if the recorded PID is confirmed dead, the orphan lock can be recovered immediately;
- if the PID is missing, malformed, unsupported, or indeterminate, Radar falls back to the existing conservative age-based stale-lock policy.

This addresses cases such as Ctrl+C or process termination leaving a fresh lock file behind, without weakening protection for a genuinely active process.

The Windows implementation uses process-liveness inspection rather than assuming that lock age alone proves whether the original process still exists.

## Result recovery

Historical analog result/protocol resolution follows the same principle. A temporarily unavailable result page does not automatically invalidate the analog if another public section or a valid cached artifact can supply the same evidence.

## State-transition evidence guardrail

A procurement or opportunity missing from one bounded recurring run is not treated as proof of closure/inactivity.

Explicit observed evidence is required for `PROCUREMENT_CLOSED` and `OPPORTUNITY_NO_LONGER_ACTIVE`. This prevents bounded search scope, page budgets, result ordering, or temporary EIS gaps from generating false downstream alerts.

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

## Test-environment isolation

R4F.2.1 removes host Telegram credential variables from the pytest environment for each test. Production runtime behavior is unchanged: real environment credentials still take precedence where intended.

This keeps tests deterministic and prevents workstation credentials from altering assertions or appearing in test-failure output.

## Operational validation

The resilience chain has been exercised beyond unit tests:

- production preflight succeeded with Telegram enabled;
- controlled live discovery runs completed with exit code `0` and no residual lock;
- detail-verification degradation retained provisionally-open candidates during temporary detail-page unavailability;
- native Windows TLS trust eliminated the Python-only certificate-chain failure without disabling verification;
- source recovery converted stale direct URLs into live canonical detail sources when EIS exposed them;
- cross-run last-known-good source persistence was confirmed in the production SQLite state;
- production runs demonstrated previously proven canonical URLs returning repeated HTTP `404` responses;
- proven-canonical retry execution and outcome were observed through structured R4H.6.1 diagnostics;
- later resolver attempts recovered some procurements live after failed proven-canonical retries, demonstrating that same-run `404` / no-match can be transient;
- R4H.7 production validation correctly classified recent-proof unresolved cases as `PROVEN_SOURCE_TEMPORARILY_UNAVAILABLE` rather than `SOURCE_URL_NOT_FOUND`;
- live Telegram end-to-end delivery succeeded through the real alert pipeline;
- Windows Startup deployment was validated by reboot/login and continued three-hour background cycles.

The accepted local suite at the R4H milestone is `297 passed`.

## Repository safety

Source snapshots, cached EIS pages, downloaded protocols, SQLite state, browser state, generated reports, runtime logs, locks, and credentials are runtime artifacts and should remain ignored by Git.
