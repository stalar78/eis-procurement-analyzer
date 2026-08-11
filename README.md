# EIS Procurement Analyzer

EIS Procurement Analyzer is a rule-based Python pipeline for collecting, downloading, classifying, and analyzing public procurement materials from the Russian EIS system.

The repository includes **EIS Procurement Radar**: a stateful decision-support layer that discovers active procurements, verifies whether applications are still open, estimates technical fit, searches historical analogs, extracts competition evidence, detects failed-procurement/republication opportunities, enriches selected candidates with documents, and produces explainable recommendations for manual review.

The project is **not** a legal, financial, automated participation, or automated bidding service.

## Current status

- Radar version: `0.3.6-r3b1-live-failure-discovery`
- Historical result extraction version: `0.3.4-r3a-result-extraction`
- Opportunity intelligence version: `0.3.5-r3b-opportunities`
- Full local test suite at the R3B.1 milestone: `147 passed`
- R3A historical intelligence is accepted for controlled recurring use.
- R3B opportunity intelligence is accepted offline and its live failed-history path has now been validated against real EIS data.

The live R3B.1 validation proved that `FAILED_ONLY` can retrieve completed/failed historical procedures, resolve protocol evidence, and classify real weak-competition outcomes. The bounded validation found two real `SINGLE_APPLICATION` cases with high-confidence protocol evidence. No republication relation was found in the bounded same-customer follow-up sample, and none was forced.

The system is intentionally conservative: missing evidence remains missing, partial result data contributes only to supported metrics, and low-confidence signals remain explicitly low-confidence.

## Radar pipeline

```text
EIS active search
    -> discovery and deduplication
    -> preliminary eligibility/scoring
    -> detail-page open verification
    -> historical analog search
    -> analog similarity/category gating
    -> result/protocol extraction
    -> competition metrics + confidence
    -> history-adjusted assessment
    -> failed-procurement / republication opportunity intelligence
    -> controlled document enrichment
    -> deep technical assessment
    -> final manual-review recommendation
```

## What the project demonstrates

- Playwright-based EIS discovery and page traversal;
- active-procedure search with explicit stage/deadline verification;
- separate active and failed-history discovery modes;
- SQLite-backed run, observation, enrichment, historical, and opportunity state;
- resumable new/changed procurement processing;
- controlled document enrichment with budgets and artifact hashing;
- defensive attachment downloads and format validation;
- extraction from DOCX, DOC, PDF, XLSX, XLS, ZIP, RAR, RTF, TXT, HTML, and selected binary sources;
- strict evidence-backed field extraction and conflict handling;
- source recovery and last-known-good caching for unstable EIS URLs;
- explainable historical analog search and category gating;
- source-aware Russian normalization;
- 44-FZ and 223-FZ result/protocol resolution;
- multi-document historical result assembly;
- separate participant, reduction, and winner samples;
- competition metrics, historical confidence, and dumping-risk signals;
- explicit failed-procurement classification;
- explainable republication matching;
- separate opportunity scoring with hard safeguards;
- bounded live failure-history discovery using its own historical lookback window;
- transactional reporting with `latest` vs `latest_attempt` semantics;
- synthetic regression fixtures and automated tests.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Methodology](docs/METHODOLOGY.md)
- [Outputs](docs/OUTPUTS.md)
- [Radar overview](docs/RADAR.md)
- [Live discovery](docs/RADAR_LIVE_DISCOVERY.md)
- [Document enrichment](docs/RADAR_ENRICHMENT.md)
- [Historical intelligence](docs/RADAR_HISTORICAL_INTELLIGENCE.md)
- [Resilience and recovery](docs/RADAR_RESILIENCE.md)
- [Analog selection](docs/RADAR_ANALOG_SELECTION.md)
- [Historical result extraction](docs/RADAR_RESULT_EXTRACTION.md)
- [R3B opportunity intelligence](docs/RADAR_OPPORTUNITIES.md)
- [Synthetic examples](examples/README.md)
- [Security policy](SECURITY.md)

## Main entry points

- `collect_results.py` — collects EIS search-result cards and local datasets.
- `score_results.py` — lightweight rule-based scoring and ranking.
- `collect_candidate_details.py` — procurement traversal and importable direct-target collection used by Radar enrichment.
- `analyze_candidate_documents.py` — document extraction/classification and importable directory analysis.
- `python -m radar.runner` — stateful Radar orchestration.

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

Optional local tools can improve extraction of legacy formats: LibreOffice, 7-Zip/`unrar`, and `antiword`.

## Configuration

Start from:

```text
config/radar.example.yaml
config/search_profiles.yaml
```

The example configuration covers discovery budgets, open-status verification, scoring thresholds, enrichment limits, historical search, analog similarity, result collection, dumping-risk thresholds, cache windows, and the R3B `opportunities` section.

The opportunity section includes bounded failure-history search, republication windows and relation thresholds, and opportunity-score thresholds. It is disabled by default until explicitly enabled for a controlled run.

## Safe validation

Offline regression tests do not require live EIS access:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The original analyzer regression mode is also available:

```powershell
.\.venv\Scripts\python.exe .\analyze_candidate_documents.py --run-regression-tests
```

## Controlled live discovery

```powershell
.\.venv\Scripts\python.exe -m radar.runner `
  --profile medium_complexity_web `
  --discovery-mode ACTIVE_ONLY `
  --verify-open-from-detail `
  --limit 100 `
  --max-pages 2 `
  --output outputs\radar_active `
  --db data\radar_active.db `
  --verbose
```

Use `python -m radar.runner --help` as the final source of truth for the current CLI surface.

## Historical intelligence

R3A searches completed procurements, selects explainable analogs, resolves result/protocol evidence, and calculates market signals such as participant counts, reductions, repeated-winner evidence, no-application/all-rejected rates, and confidence.

Participant and reduction samples are independent: valid participant evidence may contribute even when final price is unavailable, and valid price evidence may contribute even when participant count is missing.

Historical evidence adjusts but does not overwrite the preliminary assessment. Missing history does not automatically become `REJECT`.

## R3B opportunity intelligence

R3B looks for a different kind of signal: a current procurement may be interesting because a related historical procedure had weak or unsuccessful competition.

The failure model distinguishes:

- `NO_APPLICATIONS`;
- `SINGLE_APPLICATION`;
- `ALL_APPLICATIONS_REJECTED`;
- `NO_ADMITTED_APPLICATIONS`;
- `PROCUREMENT_CANCELLED`;
- `PROCEDURE_DECLARED_UNSUCCESSFUL`;
- `CONTRACT_NOT_CONCLUDED`;
- `UNKNOWN_FAILURE`.

Zero applications and rejection-based outcomes require explicit evidence. Missing winner or missing price is not enough.

Republication matching is explainable and can use same customer, functional/title similarity, budget, procedure, region, temporal proximity, and explicit references.

The opportunity score is separate from dumping risk. A historical failure cannot override core safeguards: a technically rejected, closed, or unverified current procurement cannot become a high-priority opportunity merely because the prior procedure had weak competition.

R3B also persists failure events, republication links, opportunity assessments, and transitions for later comparison across runs.

### R3B.1 live validation

R3B.1 fixed two live-path defects discovered during controlled validation:

- the initial zero-card symptom came from a real search card failing detail verification with an unavailable detail URL, not from an empty EIS search;
- failed-history discovery incorrectly inherited the short active-discovery publication window instead of the configured historical lookback.

After the fixes, a bounded historical-first run using `FAILED_ONLY` returned 50 real historical cards for the first query, inspected five result/protocol candidates, and confirmed two `SINGLE_APPLICATION` events with high-confidence protocol evidence.

Same-customer follow-up searches found no later distinct procurement in the bounded sample for those two cases. This is recorded as no relation found, not as a failed parser or a fabricated republication.

## Repository safety

Generated/live data must remain local. The repository intentionally excludes runtime outputs, SQLite databases, downloaded procurement documents, browser authentication state, live EIS HTML/protocol artifacts, caches, and temporary run directories.

Tracked fixtures are synthetic/test-oriented and should not be replaced with real procurement corpora.

## Known limitations

- The system is deterministic and rule-based; it does not currently use external LLM APIs, embeddings, or ML ranking.
- Historical similarity and republication scoring are heuristic and explainable, not probabilistic.
- Historical confidence may remain low with small usable samples.
- Some 44-FZ/223-FZ result layouts may still require parser maintenance.
- Winner evidence is often sparser than participant or reduction evidence.
- EIS pages may intermittently return unavailable or inconsistent responses.
- Live republication matching is implemented but has not yet been demonstrated with a real bounded pair in the current validation set.
- The project does not bypass CAPTCHA, authentication boundaries, or closed access.
- Final participation decisions require human legal, commercial, and technical review.

## Development direction

The failure-history path is now live-validated. The next useful work should focus on operationalizing the Radar for repeated runs and surfacing newly changed/high-value opportunities, while preserving bounded collection and human review.

## License

MIT License. See [LICENSE](LICENSE).
