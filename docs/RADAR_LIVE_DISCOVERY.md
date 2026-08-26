# Radar Live Discovery

## Goal

The live discovery layer finds procurements that are actually relevant to current participation rather than mixing active and completed EIS procedures.

## Discovery modes

Supported modes include:

- `ACTIVE_ONLY`
- `ACTIVE_AND_RECENT`
- `ALL_STATUSES`
- historical modes used by the historical layer.

For operational monitoring, `ACTIVE_ONLY` is the default approach.

## Search requests

`radar.search_request` separates configuration from request serialization. Search filters, pagination, sort order, date windows, law, and stage are represented explicitly and fingerprinted.

The implementation was introduced after live auditing showed that an older search URL contained `pc=on`, which EIS treated as a completed-procedure filter. Active discovery therefore uses explicit active-stage filtering and does not silently inherit completed-stage parameters.

## Status normalization

`radar.open_verification` maps raw EIS labels into normalized states such as:

- `APPLICATION_SUBMISSION`
- `PRICE_SUBMISSION`
- `COMMISSION_REVIEW`
- `COMPLETED`
- `CANCELLED`
- `CONTRACT_SIGNED`
- `SUSPENDED`
- `UNKNOWN`

A raw status string alone is not sufficient to make a procurement eligible.

## Provisional open eligibility

A procurement is provisionally open only when the available search-card evidence supports the active stage and the application deadline is still in the future.

Completion and cancellation signals override a future deadline.

## Detail-page verification

For bounded provisional candidates, Radar can open the common-information page and verify:

- procurement number;
- current status;
- application deadline;
- cancellation state;
- source URL consistency.

Verification states distinguish confirmed-open procedures from explicit negative/conflicting evidence and temporarily unavailable detail pages.

### R4F.3 degradation policy

Detail verification is an evidence-strengthening layer, not a requirement that can silently erase otherwise valid active-search evidence when EIS detail pages are temporarily unavailable.

The current policy is:

- `VERIFIED_OPEN` -> keep the candidate;
- `DETAIL_UNAVAILABLE` -> keep the provisionally-open candidate and record the unavailable verification;
- candidate not attempted because `verify_top_candidates_limit` was reached -> keep the provisionally-open candidate and record that verification was skipped due to the limit;
- `VERIFIED_CLOSED` -> reject the candidate;
- `VERIFIED_CANCELLED` -> reject the candidate;
- `STATUS_CONFLICT` -> keep the existing conservative rejecting semantics;
- `DEADLINE_CONFLICT` -> keep the existing conservative rejecting semantics.

`DETAIL_UNAVAILABLE` is **not** converted into `VERIFIED_OPEN`. Radar preserves the candidate because the available evidence remains provisional rather than because the detail page confirmed it.

If provisional candidates existed but explicit negative verification rejects all of them, diagnostics can report `ALL_PROVISIONAL_CANDIDATES_REJECTED_BY_DETAIL_VERIFICATION` instead of the less specific `NO_OPEN_CANDIDATES_FOUND`.

A controlled live validation of R4F.3 observed 13 search cards with active raw status, future deadlines, and provisional-open eligibility. All 13 detail checks were temporarily unavailable. Under the degradation policy all 13 remained discovery candidates; before R4F.3 the same condition incorrectly reduced the final candidate set to zero.

### R4H source-resilience policy

R4H hardens detail verification against unstable EIS source URLs without weakening the evidence contract.

The source chain now behaves conservatively:

1. fetch the current direct source;
2. if a different recent last-known-good source exists, live-fetch and validate it;
3. if the current source itself is a recently proven canonical source and fails with a bounded transient condition such as `404`, request error, `429`, or selected `5xx`, perform one additional same-URL live retry;
4. if live verification still fails, use the existing bounded exact-number / alternate source resolver;
5. accept `VERIFIED_OPEN` only from live content that contains the expected procurement identity and passes the existing detail verification.

Successful source URLs are remembered across runs only after live validation. Remembered metadata never becomes fresh evidence by itself.

R4H.6.1 preserves retry diagnostics through later recovery or final failure. Production outputs can therefore distinguish whether a proven canonical retry was attempted, whether it succeeded, its safe failure code / HTTP status, and what the subsequent resolver did.

R4H.7 changes absence certainty when recent proof exists. If a procurement has a recent live-validated source but the current direct/retry/recovery chain ends with `NOT_FOUND_CONFIRMED`, Radar keeps the result as `DETAIL_UNAVAILABLE` and records:

- `detail_failure_code = PROVEN_SOURCE_TEMPORARILY_UNAVAILABLE`;
- `detail_recent_proven_source = true`;
- `detail_absence_certainty = DEGRADED_BY_RECENT_PROOF`.

This does **not** make the procurement `VERIFIED_OPEN`. It only prevents one unstable EIS run from being treated as durable proof that a recently verified source disappeared.

For procurements without recent proven source evidence, existing `SOURCE_URL_NOT_FOUND` semantics remain unchanged.

Live production validation of R4H observed previously verified canonical URLs returning repeated HTTP `404` responses while a later bounded resolver attempt sometimes recovered the same procurement live in the same run. This is the operational evidence behind the degraded absence-certainty rule.

## Query budgets

Live discovery is bounded. Configuration can limit:

- total queries;
- pages per query;
- total pages;
- unique cards;
- verification count;
- publication/update windows.

Fallback may broaden the date window or try additional source-aware queries, but should not silently fall back to closed procedures when the goal is live participation.

A budget diagnostic such as `PAGE_BUDGET_REACHED` can therefore be a normal bounded-run outcome rather than an execution failure.

## Search diagnostics

Discovery reports preserve operational evidence including:

- query/profile;
- requested filters;
- page number;
- filter fingerprint;
- cards found;
- normalized status distribution;
- future-deadline count;
- provisional-open count;
- detail verifications attempted;
- verified-open / verified-closed / verified-cancelled counts;
- status/deadline conflicts;
- `detail_unavailable`;
- structured detail failure-code counts/examples;
- source strategy / resolver status;
- proven-canonical retry attempt/outcome fields when applicable;
- recent-proven-source / degraded absence-certainty fields when applicable;
- `detail_verification_skipped_due_to_limit`;
- `detail_verification_rejected`;
- parse warnings and failure codes.

Sensitive session data, raw exception text, raw HTML, and unredacted diagnostic source identifiers are not part of public diagnostics.

## Example

```powershell
.\.venv\Scripts\python.exe -m radar.runner `
  --profile medium_complexity_web `
  --discovery-mode ACTIVE_ONLY `
  --published-within-days 120 `
  --max-pages 2 `
  --max-total-queries 5 `
  --max-total-pages 10 `
  --verify-open-from-detail `
  --output outputs\radar_active `
  --db data\radar_active.db `
  --verbose
```

## Interpretation

Discovery answers whether a procurement is a plausible live candidate and records the confidence/evidence state of that decision. Temporary inability to open a detail page is therefore represented as unavailable verification rather than silently rewritten as a closed procurement.

Discovery does not establish technical feasibility or market attractiveness. Those questions are handled by historical intelligence, scoring, and document enrichment.
