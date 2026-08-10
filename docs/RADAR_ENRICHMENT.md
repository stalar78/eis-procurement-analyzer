# Radar Document Enrichment

## Goal

The enrichment layer performs bounded document collection and deep analysis only for candidates that survive preliminary and historical screening.

This avoids downloading and analyzing full document sets for every discovered procurement.

## Selection

Typical enrichment candidates are `PRIORITY` or `REVIEW`, subject to configurable score, deadline, cache, and per-run limits.

Historical intelligence can adjust enrichment priority before documents are downloaded.

## Live collection

`radar.live_collection` and the compatibility API in `collect_candidate_details.py` allow Radar to start from a procurement number and validated EIS source URL.

The collector can traverse available sections such as:

- common information;
- documents;
- results;
- events;
- protocols;
- contracts when accessible.

A single browser/context can be reused across a bounded batch.

## Download safety

Accepted artifacts are validated before registration:

- HTTP/browser response status;
- content type;
- content disposition where available;
- file signature;
- non-empty content;
- maximum file size;
- SHA-256 hash.

HTML error/interstitial pages are not accepted as procurement documents.

Filenames and paths are sanitized to prevent traversal outside the procurement root.

## Artifact registry

`radar.artifact_registry` records artifact identity and provenance, including source URL, section, safe local path, content type, size, SHA-256, download/cache state, and timestamps.

A stable document-set fingerprint allows Radar to distinguish genuine document changes from unrelated card changes such as a deadline update.

## Cache and resume

Completed unchanged artifacts can be reused. Interrupted runs can resume without redownloading known-good files.

Typical retryable conditions include transient network failures, rate limiting, TLS resets, and timeouts. Permanent validation errors are kept distinct from transient failures.

## Analyzer integration

After usable documents are available, enrichment calls the importable analyzer API exposed by `analyze_candidate_documents.py`.

The deep assessment maps analyzer output into Radar-specific fields such as:

- technical participation verdict;
- economic viability;
- solo/AI execution fit;
- estimated effort/cost;
- platform and integration risks;
- evidence completeness;
- blockers, conditions, and unresolved questions.

Preliminary and historical assessments remain preserved rather than being overwritten.

## Dry run

A dry run may discover and plan candidates but must not download procurement documents or mutate normal published run state.

## Limits

The example configuration exposes controls for:

- documents per procurement;
- total download volume;
- maximum single-file size;
- download/analysis timeouts;
- retry attempts;
- per-decision candidate limits;
- refresh intervals.

## Principle

Enrichment is expensive relative to card-level and historical screening. It should therefore be applied selectively, with explicit budgets and inspectable evidence.
