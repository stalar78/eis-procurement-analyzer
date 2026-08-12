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
- `detail_verification_skipped_due_to_limit`;
- `detail_verification_rejected`;
- parse warnings and failure codes.

Sensitive session data and cookies are not part of diagnostics.

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
