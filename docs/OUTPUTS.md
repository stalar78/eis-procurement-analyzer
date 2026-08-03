# Outputs

## General rule

All real analysis outputs are local generated data. They may contain procurement identifiers, customer names, document text, prices, links, and other material that should not be committed to the public repository.

Only synthetic examples under `examples/` are intended for publication.

## Main consolidated outputs

### `procurement_analysis.xlsx`

Workbook for manual review. Depending on the analysis run, sheets may include:

- Summary;
- All procurements;
- Top candidates;
- Technical participation;
- Market results;
- Manual market review;
- Prices and competition;
- Functional scope;
- Requirements;
- Infrastructure;
- Risks;
- Data quality;
- Document classification;
- Evidence index;
- Unresolved fields;
- Extraction errors.

The exact sheet set is determined by the current writer implementation and available data.

### `procurement_analysis.json`

Structured representation of analyzed procurement cards, extracted values, statuses, scores, verdicts, and quality information.

### `procurement_analysis.csv`

Flattened table intended for filtering, comparison, and downstream analysis.

### `analysis_summary.md`

Human-readable summary of the current analysis run.

## Extraction and classification outputs

### `extraction_manifest.csv`

Tracks document extraction attempts and results.

Typical information:

- procurement identifier;
- source path;
- original filename;
- detected format;
- extraction status;
- extracted text length;
- extractor or fallback used;
- error details.

### `document_classification.csv`

Records the assigned document class and the signals used for classification.

Typical classes include technical specifications, contracts, NMCK calculations, application requirements, clarifications, protocols, notices, signatures, and other files.

### Per-procurement extracted material

The analyzer can create local folders containing extracted text, intermediate files, and evidence material for individual procurements.

These folders are deliberately excluded from Git.

## Evidence and quality outputs

### `evidence_index.csv`

Connects accepted fields to supporting material.

Typical columns may include:

- procurement identifier;
- field;
- value;
- source document;
- document class;
- location;
- excerpt;
- extraction method;
- confidence.

### `unresolved_fields.csv`

Lists important fields that could not be supported by acceptable evidence.

A field may remain unresolved because:

- the required document is missing;
- the file is unreadable;
- extraction is partial;
- no acceptable pattern was found;
- candidate values were rejected;
- allowed sources conflict.

### `quality_issues.csv`

Records issues that affect completeness or reliability, such as unreadable files, partial extraction, missing document groups, and unsupported values.

### `field_conflicts.csv`

Records contradictory values found in allowed sources.

The analyzer should expose the conflict rather than silently choosing one source.

### `rejected_candidates.csv`

Stores values or matches that were considered but rejected by strict validation.

This is especially important for financial extraction, where unrelated amounts must not become final prices.

## Market and decision fields

Typical analyzed fields include:

- initial maximum contract price;
- final contract price;
- participant count;
- price reduction percentage;
- document availability statuses;
- technical complexity score;
- financial risk score;
- solo developer fit score;
- AI-assisted development fit score;
- recommended minimum price;
- recommended comfortable price;
- technical participation verdict;
- market result status;
- overall recommendation;
- manual review flags;
- exclusion from market aggregates.

Not every field is available for every procurement. Missing or unresolved values are expected and should not be replaced with guesses.

## Synthetic public examples

The public repository may contain small synthetic examples demonstrating:

- a fictional input candidate;
- a fictional analyzed result;
- document classification;
- evidence records;
- unresolved fields;
- quality issues;
- conflicts;
- a Markdown summary.

Synthetic examples must use:

- invented procurement identifiers;
- fictional customers;
- `example.invalid` URLs;
- invented filenames and excerpts;
- values that do not reproduce a real procurement record.

## Development-run aggregate figures

The local audited project artifacts confirm:

- 1,237 unique collected records;
- 15 selected candidates;
- 125 downloaded documents;
- two analyzed cases with a reduction of at least 75%;
- one analyzed case with a reduction above 90%;
- a maximum confirmed participant count of 11 in the audited analysis set.

The previously discussed claim of more than 50 participants is not supported by the audited artifacts and must not be published as a project result.

The audited `field_conflicts.csv` contained no confirmed rows, so conflicts between technical specifications and clarifications must be described as a supported capability, not as a confirmed result of the current dataset.
