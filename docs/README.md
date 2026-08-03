# Documentation

This directory contains the public technical documentation for EIS Procurement Analyzer.

## Documents

- [Architecture](ARCHITECTURE.md) — pipeline stages, module boundaries, source-dependent behavior, and reusable analytical concepts.
- [Methodology](METHODOLOGY.md) — document statuses, classification, strict extraction, evidence, conflicts, and decision layers.
- [Outputs](OUTPUTS.md) — generated reports, evidence and quality files, decision fields, and publication rules.

## Source of truth

The implementation and regression tests are the final source of truth for current behavior:

- `collect_results.py`
- `score_results.py`
- `collect_candidate_details.py`
- `analyze_candidate_documents.py`
- `tests/test_strict_extraction.py`

Documentation explains the architecture and public contract but must not be used to claim a feature that is absent from code.

## Public-data rule

Do not place downloaded procurement documents, page snapshots, generated analysis outputs, local datasets, screenshots with personal data, cookies, tokens, secrets, or machine-specific paths in this directory.

Use only fictional examples from `examples/` for public demonstrations.
