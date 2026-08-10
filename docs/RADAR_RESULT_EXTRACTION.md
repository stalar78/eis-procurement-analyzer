# Radar Historical Result Extraction

## Purpose

The result-extraction layer converts selected historical analogs into usable competition evidence. It resolves public EIS result/protocol sources, extracts supported fields, assembles them across multiple documents/pages, and records field-level provenance.

Current extraction version: `0.3.4-r3a-result-extraction`.

## Why a dedicated layer is needed

A procurement's competition data is often split across multiple result sources. One page may contain the NMCK, another the application list, and another the final price or winner. Requiring one fully populated source would discard valid partial evidence.

## 44-FZ and 223-FZ paths

The implementation distinguishes 44-FZ and 223-FZ result navigation because the public EIS layouts differ.

Examples of supported public sources include:

44-FZ:

- supplier-results;
- protocol main information;
- protocol bid/application lists;
- protocol document sections.

223-FZ:

- protocol lists;
- protocol common information;
- bid information;
- result review/comparison/grade pages;
- contract information where appropriate.

Endpoint/layout assumptions are source-specific and may require maintenance as EIS changes.

## Protocol classification

Result documents are classified before extraction. Distinguishing final protocols, auction protocols, application-review protocols, contracts, result notices, clarifications, and unrelated documents reduces the risk of using the wrong numeric value.

Classification uses available filename, section, link text, and content signals.

## Strict field rules

Accepted competition fields come only from defensible sources.

### NMCK

Supported by procurement card/notice or structured procurement data.

### Final price

Supported by final result/protocol data or an explicit concluded-contract result. Security amounts, application identifiers, percentages, and unrelated monetary values must not be promoted to final price.

### Participant/admitted counts

Supported by structured result or protocol evidence that represents actual applications/participants. Repeated auction-history rows must not inflate participant counts.

### Winner

Supported by explicit final protocol/result/contract evidence.

### Reduction

Calculated only from valid NMCK and final price when `final_price <= nmck`.

## Multi-document assembly

`radar.result_extraction` can assemble an `AssembledHistoricalResult` from multiple sources belonging to the same procurement.

Per-field provenance is preserved for:

- NMCK;
- final price;
- participant count;
- admitted count;
- winner;
- reduction inputs.

Conflicts lower confidence rather than being silently reconciled.

## Completeness states

Historical results can be complete or partially usable.

A result with valid participant evidence but no final price may still contribute to participant metrics. A result with a valid price pair but missing participant count may still contribute to reduction metrics.

This produces separate metric samples instead of one all-or-nothing sample.

## Metric samples

Competition aggregation tracks independent evidence pools such as:

- participant sample size;
- reduction sample size;
- winner sample size;
- complete-result sample size.

Each metric can preserve the procurement numbers that contributed to it.

## Caching and versioning

Result extraction has its own version so parser changes can invalidate extracted values without unnecessarily discarding valid downloaded source artifacts.

Cached result/protocol evidence can be reused when public EIS pages are temporarily unavailable, with freshness reported explicitly.

## Current limitations

- some protocol layouts may still be unsupported;
- some publicly reachable result pages do not expose enough competition data within bounded traversal;
- winner evidence can be much sparser than participant or reduction evidence;
- small usable samples should remain low-confidence.

The correct behavior for unsupported or unavailable fields is to leave them missing and report the limitation rather than infer a value.
