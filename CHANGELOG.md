# Changelog

## [Unreleased]

### Added

- `dataform/`: Dataform models that build the output tables from
  py-common's raw tables in BigQuery, in three layers: bronze (the raw
  tables), silver (the mappings as reference tables and one cleaned row
  per source row) and gold (the tables of `docs/output_contract.md`,
  with the same columns and identifiers). Assertions stop a run on the
  same problems that stop `wrangle.py`, check each gold table against
  its schema file, and can compare every table with the golden or
  scenario files. `hww_silver.data_quality_issues` lists what the data
  quality report lists. `docs/dataform.md` covers the GCP set-up; the
  models compile but haven't run on BigQuery yet.
- A Dataform CI workflow: the reference data built from `mappings/`
  must be current and the models must compile.
- `docs/rules.md` names the Dataform model behind each rule.
- JSON Lines exports of the SharePoint lists: a WAS or peer source whose
  `file` ends in `.jsonl` reads through py-common's
  `GraphJsonLinesContract`, configured with `field_map`, `metadata_map`,
  `excluded_fields` and `site_time_zone` in its config section.
- `tests/data/inputs/dummy_was_database.jsonl`: the dummy WAS workbook as
  a Graph list export, written by `scripts/make_was_jsonl.py` and mapped
  by `tests/data/was_graph.toml`. `tests/test_was_jsonl.py` lands it and
  checks that it builds the same tables as the workbook.
- A WAS request with no Participant ID in a JSON Lines export gets its id
  from the SharePoint item ID (`WAS-item21`), which stays the same when
  earlier items are deleted. A workbook still uses the row (`WAS-row22`).
- `config.gcp.dummy.toml`: `config.gcp.toml` with the dummy workbooks,
  for proving a GCP set-up before the real exports exist.
- `privacy.org_overrides_file` and the Dataform variable
  `org_overrides_table`: real organisation overrides stay out of Git.
  A committed `mappings/org_overrides.csv` with rows is refused.
- Dataform checks that run before any gold table: keys, contact details,
  row counts, freshness, payload keys and duplicate loads.
- `hww_gold.published_loads`, recording the loads behind each published
  run, which the row-count check compares with.
- `docs/production.md`: the production inputs, access, retention,
  rollback and acceptance steps.
- `.github/workflows/pipeline.yml`, and a CI job publishing `dataform/`
  to the `dataform` branch.

### Changed

- **A source that loses more than `max_row_drop` of its rows holds
  publication**, in `wrangle.py` and in Dataform. It used to be a
  warning. `allow_row_drop` publishes an agreed reduction.
- `wrangle.py` refuses a load older than `max_load_age_hours` on the GCP
  route, and a workbook with formula cells holding no saved value.
- One publication lease covers the read and publish of a GCP run.
- `raw_latest_loads` is a table built once per Dataform run, and picks
  the highest GCS generation. `survey_other_text` is always rebuilt, and
  empty when free text is switched off.
- `HeadingCheckedContract` is gone: `Column` type `"any"` from py-common
  does its job.

### Fixed

- `hww-ingest` (and so `hww-run`) exits 2 for an unexpected error,
  logged with its traceback, as `hww-wrangle` does. It used to exit 1,
  the code for a problem a person can fix.
- A failure in one landing folder no longer stops the others loading;
  the run still exits 2.
- Spelling ties in `dim_employer` no longer depend on the order Python
  happens to count them.
- Error messages no longer repeat workbook values.
- `constraints.txt` pins certifi 2026.10.19, which fixes
  PYSEC-2026-4320, and py-common at the commit whose image builds.
- JSON log lines carry py-common's structured fields such as `outcome`,
  so log-based alerts can match them.
- Out-of-date statements in `docs/architecture.md`, `docs/gcp.md` and the
  README.

### Changed

- Ingestion uses py-common's raw JSON tables (py-common 0.3.0, which has
  no other load route). `python ingest.py` loads each sheet's allowed
  columns into a raw table (`hww_signups`, `hww_survey`, `hww_was`,
  `hww_peer`), one JSON payload per row with the file, version and Excel
  row it came from; `landed.py` reads them back. Output tables are
  unchanged.
- One pipeline per workbook (`landing.workbooks`): the monitoring
  workbook's Account signups and Survey info sheets load together, so a
  problem on either sheet quarantines the whole upload and the two tables
  always come from the same upload. `ingest()` results and the upload
  service's pipelines are keyed by landing folder.
- `LocalRawWarehouse` replaces `LocalTableWarehouse` on laptops: each
  load of a table is an NDJSON rows file and an audit record in
  `landed/<table>/`, committed by writing the audit record last. Delete
  any `landed/` folder from earlier runs.
- `RowNumberedContract` is `HeadingCheckedContract`: the Excel row number
  comes from py-common's `row_number`, so no column is added.

### Removed

- `landing.ROW_COLUMN`, `ROW_FIELD`, `LOADED_AT` and the Parquet tables.
- The upload-triggered Cloud Run service (`hww_dashboard.service`, the
  `service` extra and its Pub/Sub and Eventarc set-up). The daily run picks
  up a late or corrected file the next morning.
- `file_pattern` and the newest-export selection behind it
  (`newest_match`, `date_in_name`, `landing.NewestSource`). Every source now
  has one exact `file` name.
- `SourceContract.undeclared`, which was always empty.
- `docs/readiness.md`, last assessed on 2026-10-18. Its open limitations
  moved to `docs/production.md`.

### Added

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

- Survey answers come from the Survey info tab of the monitoring workbook
  instead of the survey tool's export: `[survey]` in both configs and the
  test config, and `mappings/survey_columns.csv`, describe that tab.
  `response_id` is its Count, which can move if rows are renumbered or
  deleted (`docs/identifiers.md`). No output table's columns change.
- One upload of the monitoring workbook, to `hww/signups/` (or
  `landing/signups/`), loads both `hww_signups` and `hww_survey`. Sources
  that name the same workbook share a landing folder
  (`landing.landing_folders`).
- `requirements.txt` installs py-common (the `landing` extra).
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

- The synthetic survey export in `tests/data/inputs/`. The synthetic
  monitoring workbook has a Survey info sheet instead.
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
