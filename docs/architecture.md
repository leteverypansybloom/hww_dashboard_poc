# How this prototype fits the HWW data platform

This project is a **prototype**: it shows the dashboard pages and the
numbers behind them, end to end, on a laptop. The production route for
Healthy Working Wales (HWW) data is different:

```
py-common  →  BigQuery raw tables  →  Dataform  →  Power BI
(landing)     (one per worksheet)     (cleaning,     (reports)
                                       modelling)
```

The prototype does every one of those jobs itself, in Python:

```
input folder  →  hww_dashboard.wrangle  →  output/*.csv       →  Streamlit pages
(4 workbooks)    (read, clean, model)     or an interim         (dashboard_data
                                          BigQuery dataset         + dashboard)
                                          (star schema)
```

Until the Dataform models exist, the pipeline runs for real: on
laptops it writes CSV files, and in GCP it loads the same tables into
an interim BigQuery dataset (`[output] target = "bigquery"`), with the
table names and schemas Dataform is expected to produce, so reports
built on it later move to Dataform's tables by changing the dataset
name (`DECISIONS_en.md`, 2026-10-18).

This page says which prototype piece corresponds to which production
stage, what the package refactor did and did not change, and what a
move to the production backend would involve. That move is **separate
work**: nothing here depends on it.

## The production route

The shared ingestion library, py-common, is documented in its own
repository (README, `docs/RAW_JSON_VS_CONTRACT_VALIDATION.md`,
`docs/RAW_TABLE_LAYOUT.md`, `docs/GCP_SETUP.md`). In short:

- **py-common lands the files.** Each workbook arrives in its own
  folder of a GCS landing bucket (SharePoint files are copied there
  first) and keeps one agreed file name. A contract per workbook reads
  the heading row, loads only the columns it lists, leaves personal
  columns out, and warns rather than rejects when the layout drifts.
  Every row of every configured worksheet is inserted into a raw
  BigQuery table (`raw_hww.hww_was_database`, for example) as a JSON
  payload, with the file's version, an audit record and a kept copy of
  the original file.
- **Dataform cleans and models.** SQL picks the latest upload of each
  file, types the values, sets bad rows aside, merges duplicate
  employers and builds the tables the reports read.
- **Power BI reports** from the cleaned Dataform datasets, never from
  the raw tables.

py-common's scope stops at the raw load. Business rules, mappings,
employer matching, metrics and report design are downstream of it by
design (its `INGESTION_FRAMEWORK_GUIDE.md`, section 8).

## Where each prototype piece would live

| Prototype piece | What it does | Production home |
|---|---|---|
| `input_folder`, `input_file`, `newest_match` | Find each workbook in a local folder; the survey export is the newest by the date in its name | py-common `GCSSource`, one landing folder per workbook, fixed names |
| `read_sheet`, `require`, `check_config` | Read a sheet by name or position below a heading row; stop with a clear message on missing files, sheets or columns | py-common `Contract` (heading row, listed columns, warn or quarantine) |
| `COLUMNS`, survey `drop` roles, `keep_other_free_text` | Never write personal columns or free text (the tests check against `[privacy]` in the config) | py-common contracts' `excluded` columns (personal data never loaded), then Dataform's selected columns |
| `clean_text`, `to_date`, `drop_blank_rows` | Tidy cells, read dates day-first, skip blank rows | Dataform staging models (`SAFE_CAST`, trimming) |
| `mappings/*.csv`, `map_value`, `map_bands` | Map messy labels to agreed bands | Dataform reference tables loaded from the same CSVs |
| `build_dim_employer`, `pick_value`, `org_overrides.csv` | One employer per organisation, explainable tie-breaks | Dataform employer model (identity resolution) |
| `build_engagement`, `build_survey_tables`, `build_dim_date`, `unpivot_*` | The star schema in `output/` | Dataform mart tables |
| `data_quality_report.md`, `InputError` | Structural stops and value-level notes | py-common warnings and audit records, Dataform assertions and quarantine tables |
| `dashboard_data` | Every metric: Figure 13 %, monthly counts, employer summary | Power BI measures, or Dataform aggregate tables |
| `dashboard`, `.streamlit/config.toml` | Pages, charts and HWW branding | Power BI report pages and theme |

## What the refactor changed, and what it kept

Changed: the code is now an installable package (`src/hww_dashboard`)
with normal imports, self-contained tests (synthetic inputs in
`tests/data/`, a fixed clock), PEP 8 at 79 characters, and the same
Black, Ruff and mypy versions as py-common.

Kept on purpose:

- **The backend.** The prototype still reads the workbooks from a
  folder with pandas and openpyxl. It writes CSV files that the
  Streamlit app reads or, since 2026-10-18, BigQuery tables through
  the optional `bigquery` extra (google-cloud-bigquery). It has no
  dependency on py-common.
- **Every output.** The CSVs, their columns, the identifiers
  (`employer_id`, `signup_id`, `answer_id`, ...) and the data quality
  report are byte-for-byte what the code wrote before the refactor
  (`tests/test_golden.py`).
- **The commands**: `python wrangle.py [config.toml]` and
  `streamlit run dashboard.py`, run from the project folder.

## Why the prototype does not use py-common

py-common was checked for anything the prototype's own ingestion
needs. Nothing fits without changing what the prototype does:

- **Different source.** py-common lists files in a GCS bucket (or a
  local folder, for development), each workbook with one agreed file
  name; a renamed upload is quarantined. The prototype reads four local
  files and picks the survey export by the date in its name.
- **Sheets by name only.** py-common's contracts find worksheets by
  name. The exports' sheets are named `in`, `query` and `query (1)` by
  the systems that make them, so the prototype picks three of them by
  position.
- **Different column names.** py-common names columns exactly as
  written (`Organisation Industry ` keeps its trailing space), blank
  headings `col_B` and repeats `Other_2`. The prototype trims headings
  and uses `B` and pandas-style `Other.1`, and `config.toml` and
  `mappings/survey_columns.csv` are written in those names. Switching
  would change those identifiers for no gain in the prototype.
- **Different output.** py-common's pipeline ends in a warehouse load
  with audit records and stored copies. The prototype rebuilds every
  table from all four files on every run, and has no warehouse.

Adding py-common anyway would mean wrapping it to undo these
differences. An earlier attempt did exactly that (a `py-common-ingestion`
branch); this refactor keeps the boundary instead: py-common lands
data, and the HWW rules stay here until Dataform takes them over.

## Before a migration: differences to settle

These came up while comparing the two projects. None blocks the
prototype; each needs an answer before the production route can
reproduce the dashboard.

1. **Where survey answers come from.** The prototype reads the survey
   tool's own export, downloaded with a date in its name. py-common's
   examples load the monitoring workbook's `Survey info` sheet
   (`raw_hww.hww_survey_info`), and its "one file name per workbook"
   rule would treat dated export names as separate files. Decide which
   is the source of truth; if it is the export, it needs a fixed name
   on upload.
2. **Column names in mappings.** If Dataform reuses
   `survey_columns.csv`, its column names must be translated to the raw
   payload keys (`Other.1` becomes `Other_2`, trimmed headings get
   their spaces back).
3. **Cleaning rules move to SQL.** `clean_text`, day-first dates, the
   `Y (Dec)` flag parser and the employer tie-breaks are Python here.
   The `ASSUMPTIONS` list at the end of every data quality report is
   the plain-language specification to port.

## Migrating the backend (separate work)

A suggested order, each step useful on its own:

1. **Land the workbooks with py-common** in the HWW solution repository
   (contracts, one pipeline per landing folder, the raw JSON route), as
   in py-common's `docs/GCP_SETUP.md`.
2. **Build the Dataform models** for the star schema, with the
   mappings as reference tables.
3. **Check them against this prototype.** The rules are numbered in
   [rules.md](rules.md), each with the code and tests behind it. Land
   the synthetic inputs in `tests/data/inputs/` and the scenario
   workbooks (`tests/scenarios/`) through py-common, run the models, and
   compare their tables with `tests/golden/*.csv` and the hand-worked
   `tests/scenarios/expected/*.csv`, as in
   [output_contract.md](output_contract.md). The prototype then serves
   as an executable specification.
4. **Point the dashboard at BigQuery, if it is kept.**
   `dashboard_data.load_tables` is the only place the dashboard reads
   data: swapping its CSV reads for queries against the Dataform tables
   leaves every calculation and page unchanged.
5. **Build the Power BI reports** from the same tables, using
   `dashboard_data` and the mockups as the specification for the
   measures.

## Sharing with py-common

Concrete opportunities, none of which needs the prototype to import
py-common:

- **One personal-column list.** `[privacy] personal_columns` in
  `config.toml` and the `drop` roles in `survey_columns.csv` list the
  same columns that the HWW contracts' `excluded` lists must hold. A
  test in the solution repository can check that every column listed
  here is excluded there.
- **Shared synthetic fixtures.** `tests/data/inputs/` holds copies of
  the dummy workbooks in which every personal value is a reserved
  example (`example.org`, `192.0.2.10`). py-common's `docs/` folder
  still holds the original dummy survey export, which includes an IP
  address and report links from a survey submission; the synthetic
  copies could replace it.
- **Golden outputs as acceptance tests.** `tests/golden/` is a
  ready-made expected result for the Dataform layer (step 3 above).
- **A public naming function.** If py-common exposed the heading names
  its `read_sheet` produces (as it already exposes
  `parquet.column_name()` for typed tables), the translation in point 2
  of the previous section could call it instead of copying the rules.
