# Changelog

## [0.2.0] - 2026-10-18

### Added

- BigQuery output: explicit schemas, staging loads, transactional publication,
  a report table and an append-only run history.
- Run records with input/config/mapping checksums and code/library versions.
- Rule register, SQL-portable identifier specification and independent scenarios.
- Privacy guards, source-volume checks, action summaries and protected run logs.
- Pinned dependencies, pre-commit hooks, dependency audits, coverage gates,
  Windows CI and oldest/newest dependency test jobs.
- Contributor and agent guidance, decision log, operator and GCP runbooks, MIT
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
