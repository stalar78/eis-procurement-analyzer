# R3B Opportunity Intelligence

R3B adds a separate decision-support layer for finding current procurements that may be interesting because a related historical procedure showed weak or unsuccessful competition.

Current version: `0.3.5-r3b-opportunities`.

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

## CLI and configuration

R3B adds opportunity-related CLI controls, including failed-opportunity mode, failure-history-only mode, bounded query/page/candidate/link limits, minimum opportunity score, and history refresh.

Runtime defaults are configured in the `opportunities` section of `config/radar.example.yaml`.

## Validation status

The code milestone was accepted with `142 passed` in the full local test suite. Synthetic fixtures cover zero applications, one application, all rejected, cancellation, relation scoring, temporal ordering, explicit references, closed current procedures, and technical hard rejects.

The first bounded live validation returned zero unique current cards. Therefore R3B is code/offline-accepted but still requires controlled live failure-discovery validation against real EIS data.
