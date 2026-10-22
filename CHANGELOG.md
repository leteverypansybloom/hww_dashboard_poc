# Changelog

## [Unreleased]

### Added

- An upload-triggered Cloud Run service (`hww_dashboard.service`, the
  `service` extra): it ingests the folder a workbook was uploaded to, then
  rebuilds the tables unless a file was quarantined. The daily job stays
  as a catch-up. `docs/gcp_ingestion.md`, step 9, sets it up.
- `cloudbuild.py-common.yaml`, and build steps that stage the source in a
  named bucket, for projects that don't allow the default Cloud Build
  bucket.
- Commands installed with the package: `hww-ingest`, `hww-wrangle`,
  `hww-dashboard`, and `hww-run`, which runs ingestion and then, only if
  every file loaded, the pipeline.
- A Dockerfile for the daily GCP job, built on py-common's image, with
  `cloudbuild.yaml` to build it in GCP and `config.gcp.toml` for it to
  run with. `docs/gcp_ingestion.md` covers building, deploying and
  scheduling it.

### Changed

- `requirements.txt` installs py-common (the `landing` extra). Its GitHub
  organisation is a placeholder, `<GITHUB_ORG>`, to set before installing.
- Ingestion logs through the package's logging, so `HWW_LOG_FORMAT=json`
  gives structured lines for its own and py-common's messages.

### Added

- Ingestion with py-common's typed route: `python ingest.py` checks each
  workbook against its contract (`hww_dashboard.landing`) and loads it into
  a typed table, locally or in BigQuery. With `[landed] read = true`,
  `wrangle.py` reads the newest load of those tables instead of the
  workbooks (`hww_dashboard.landed`). Output tables are identical either way.
- `landing` extra: py-common, pinned to a commit.

### Changed

- The source loaders take an inputs object (`FolderInputs`, or
  `landed.LandedInputs`) instead of the input folder.

### Removed

- `wrangle.survey_percentages` and `output_schema.tables`, which only the
  tests called. The Figure 13 scenario test now checks the dashboard's own
  `survey_question_results`.
- The dashboard no longer loads `fact_signup` and `dim_date`, which no page
  used. wrangle still writes both.

### Fixed

- Reject unexpected signup columns while allowing mixed values only in
  the explicitly named Number of sites column; require its heading.
- Select the newest matching export before ingestion, and honour file
  selection when reading existing committed load history.
- Commit local Parquet rows and embedded audit history atomically, with
  compatibility for existing separate audit.jsonl files.
- Honour allow_empty per source and select audited empty snapshots in
  both local and BigQuery readers instead of reviving older rows.
- Clarify that excluded columns remain in archived original workbooks.

## [0.2.0] - 2026-10-18

### Added

- BigQuery output: explicit schemas, staging loads, transactional publication,
  a report table and an append-only run history.
- Run records with input/config/mapping checksums and code/library versions.
- Rule register, SQL-portable identifier specification and independent scenarios.
- Privacy guards, source-volume checks, action summaries and protected run logs.
- Pinned dependencies, pre-commit hooks, dependency audits, coverage gates,
  Windows CI and oldest/newest dependency test jobs.
- Contributor guidance, decision log, operator and GCP runbooks, MIT
  licence, and process-level reproducibility tests.

### Changed

- Removed job roles and raw survey/WAS flag text from published signup tables.
- Reports name input files and checksum prefixes and start with required actions.
- Organisation matching uses a documented SQL-portable key. Check non-ASCII
  employer identifiers before moving reports between implementations.
- Outputs use LF on every OS and are excluded from git.
- Runtime dependencies split into dashboard and bigquery extras.
- Exit codes distinguish correctable input/access problems from unexpected errors.

### Fixed

- Includes the 22 commits on review/code-quality: date parsing, config and
  mapping validation, duplicate identifiers, missing values, header collisions,
  privacy exclusions, deterministic discovery and rollback of failed folder
  publication. See the git history for regression tests and individual fixes.

### Deployment status

- Live BigQuery and Cloud Run acceptance remain required. No cloud resources
  have been deployed. A human peer review, DPIA, retention and access decisions,
  remote-hosted CI execution and support ownership are still external gates.

## [0.1.0]

Initial packaged local prototype with synthetic tests and a Streamlit mockup.
