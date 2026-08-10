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

A procurement is provisionally open only when the available card evidence supports the active stage and the application deadline is still in the future.

Completion and cancellation signals override a future deadline.

## Detail-page verification

For high-ranked provisional candidates, Radar can open the common-information page and verify:

- procurement number;
- current status;
- application deadline;
- cancellation state;
- source URL consistency.

Verification states distinguish confirmed-open procedures from status/deadline conflicts and unavailable detail pages.

## Query budgets

Live discovery is bounded. Configuration can limit:

- total queries;
- pages per query;
- total pages;
- unique cards;
- verification count;
- publication/update windows.

Fallback may broaden the date window or try additional source-aware queries, but should not silently fall back to closed procedures when the goal is live participation.

## Search diagnostics

Discovery reports can preserve:

- query/profile;
- requested filters;
- page number;
- filter fingerprint;
- cards found;
- normalized status distribution;
- future-deadline count;
- provisional-open count;
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

Discovery answers only whether a procurement is a plausible live candidate. It does not establish technical feasibility or market attractiveness. Those questions are handled by historical intelligence and document enrichment.
