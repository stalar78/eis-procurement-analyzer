# R3B Opportunity Intelligence

R3B adds a separate decision-support layer for finding current procurements that may be interesting because a related historical procedure showed weak or unsuccessful competition.

Current Radar version: `0.3.6-r3b1-live-failure-discovery`.
Opportunity model version: `0.3.5-r3b-opportunities`.

## Failure events

Radar keeps distinct failure types instead of using one generic failed status:

- `NO_APPLICATIONS`
- `SINGLE_APPLICATION`
- `ALL_APPLICATIONS_REJECTED`
- `NO_ADMITTED_APPLICATIONS`
- `PROCUREMENT_CANCELLED`
- `PROCEDURE_DECLARED_UNSUCCESSFUL`
- `CONTRACT_NOT_CONCLUDED`
- `UNKNOWN_FAILURE`

Explicit evidence is required for zero applications and rejection-based states. Missing winner or missing price is not sufficient evidence.

## Republication matching

A historical failed procurement can be linked to a later procurement through an explainable relation score using customer, functional/title similarity, budget, procedure, region, temporal proximity, and explicit references.

A procurement published before the historical failure cannot be its republication.

## Opportunity scoring

The opportunity score is separate from dumping risk. It considers current technical fit, verified open status, republication confidence, previous competition weakness, budget attractiveness, and deadline feasibility.

Safeguards remain dominant: a technical hard reject, a closed procurement, or unresolved open status cannot become a high-priority opportunity only because an earlier procedure had weak competition.

`NO_APPLICATIONS` is treated as a strong weak-competition signal. `SINGLE_APPLICATION` is a moderate signal. Rejection-based failures also raise requirement-risk warnings. Cancellation and unknown failure receive no automatic competition benefit.

## State and transitions

SQLite persists failure events, republication links, opportunity assessments, and opportunity transitions. This allows later runs to detect changes in score, deadline, NMCK, open/closed state, and relation confidence.

## Live discovery split

R3B.1 validates that active and historical searches must remain distinct.

- `ACTIVE_ONLY` is for current participation candidates and retains open-status/deadline verification.
- `FAILED_ONLY` is for historical weak/unsuccessful competition and uses the opportunity-history lookback rather than the short active-discovery publication window.

A historical failed procedure does not become a current opportunity by itself.

## R3B.1 live validation

The R3B.1 milestone was accepted with `147 passed` in the full local test suite.

Controlled live validation identified two concrete defects:

1. The original zero-unique-card run was not an empty EIS search. A raw current card was found, but detail verification failed because the detail page was unavailable (`HTTP 404`).
2. The failure-history path inherited the active-discovery 30-day publication window. This prevented the intended long historical scan. The path now uses `opportunities.failure_history.lookback_days`.

A bounded historical-first validation then used `FAILED_ONLY` with a multi-year publication range and returned 50 real historical cards from the first web/software query. Five result/protocol candidates were inspected.

Two real historical failure events were confirmed:

- one `SINGLE_APPLICATION` procedure with one application and one admitted application;
- one `SINGLE_APPLICATION` procedure with one application.

Both were supported by resolved official EIS 223-FZ protocol pages and classified with `HIGH` evidence confidence.

The exact live procurement identifiers are intentionally not copied into public documentation; generated live validation artifacts remain local/ignored.

Same-customer follow-up searches for those two events returned only the source procurement after self-exclusion, so no later distinct procurement was available in the bounded sample. Therefore:

- real failure discovery: validated;
- real failure classification: validated;
- real protocol evidence extraction: validated;
- live republication relation: not demonstrated in this bounded sample;
- fabricated/forced relation: none.

This distinction is intentional. No relation is preferable to a weakly supported relation.

## CLI and configuration

R3B adds opportunity-related CLI controls, including failed-opportunity mode, failure-history-only mode, bounded query/page/candidate/link limits, minimum opportunity score, and history refresh.

Runtime defaults are configured in the `opportunities` section of `config/radar.example.yaml`.

## Current limitations

- A real live republication pair has not yet been observed in the bounded validation set.
- EIS detail/result URLs may intermittently be unavailable.
- Failure and republication scoring remain deterministic and explainable rather than probabilistic.
- Current-open opportunity generation still depends on both a validated historical relation and current eligibility safeguards.
