# HWW dashboard

A prototype of the Healthy Working Wales (HWW) monitoring dashboard.
Two steps:

1. `python wrangle.py` turns the HWW spreadsheets into tidy CSV tables in `output/`.
2. `streamlit run dashboard.py` is a Streamlit app that draws the mockup pages from those tables.

The code is the installable package `hww_dashboard` in `src/`. This
folder holds what it runs on: `config.toml`, `mappings/` and `output/`.
How the prototype relates to the production route (py-common →
BigQuery → Dataform → Power BI) is in
[docs/architecture.md](docs/architecture.md).

## Set up

Needs Python 3.11 or newer. From this folder:

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt -c constraints.txt
```

(On macOS or Linux, activate with `source .venv/bin/activate`. On
Windows, keep the venv in a short path: Streamlit fails to install in
long ones.) `requirements.txt` installs the package in editable mode
with its `dashboard`, `bigquery` and `landing` extras; `landing` is
py-common, the shared ingestion library. `constraints.txt` pins every
library to the versions CI tests, so every laptop, CI and GCP run the
same code; `python scripts/update_constraints.py` regenerates it. For
the developer tools, install `requirements-dev.txt` instead (the same
as `pip install -e ".[dev]"`), with the same `-c constraints.txt`.

**py-common comes from GitHub.** The `landing` extra installs it with
Git from its repository, pinned to a commit. Before installing:

- set `<GITHUB_ORG>` in `pyproject.toml` (the `landing` extra) to the
  GitHub organisation that hosts py-common;
- make sure Git is installed and can reach that repository (signed in,
  if it's private).

If you don't need ingestion, `pip install -e ".[dashboard,bigquery]" -c
constraints.txt` installs everything else.

**Installing also adds four commands,** which work from any folder:

| Command | Does the same as |
|---|---|
| `hww-ingest [config]` | `python ingest.py [config]` |
| `hww-wrangle [config]` | `python wrangle.py [config]` |
| `hww-run [config]` | `hww-ingest`, then `hww-wrangle` only if every file loaded: the daily job in GCP |
| `hww-dashboard` | `streamlit run dashboard.py` (start it from this folder, so it finds `output/` and the theme) |

**`ModuleNotFoundError: No module named 'hww_dashboard'`** (or
`'py_common'`) means the project isn't installed in the Python you're
running. Activate the venv you installed into (`.venv\Scripts\activate`)
and run the commands from this folder, or run the install above. To
check which Python is running:
`python -c "import sys; print(sys.executable)"` should print a path
inside `.venv`. In VS Code, also select `.venv` as the interpreter.

## Run

Run these from this folder (the dashboard's colours are in `.streamlit/config.toml`, which Streamlit only finds from here).

```
python wrangle.py
streamlit run dashboard.py
python -m pytest
```

`output/` is not kept in git, because on a working laptop it holds real
data. After cloning, build the demo tables from the synthetic workbooks
in `tests/data/inputs/` first:

```
python wrangle.py tests/data/config.toml
```

Inputs are read from the folder above this one (set in `config.toml`).
Each file is named exactly in `config.toml`. The monitoring workbook holds both Account signups
and the Survey info tab, which has the survey responses. A source can use `file_pattern`
instead, to take the newest download (by the date in its name).
If a file, sheet, column, mapping file or setting is missing, `wrangle.py` stops with a message
saying which one before writing anything. So does a source with no data rows, because an empty
upload usually means a broken export; set `allow_empty = true` in that source's section if no rows
is a real answer. A source with more than 10% fewer rows than the last published run
(`max_row_drop` in `[checks]`) is a warning instead, since edits can remove rows. The exit code
says what happened: 0 the run finished;
1 a problem a person can fix stopped it (an input, a setting, a mapping, or an output file open in
another program such as Excel), and the message says what to do; 2 an unexpected error, which is a
bug to report.
Tables, `data_quality_report.md` and `run_record.json` are written to `output/`. The run record
says what produced the tables: each input file's name, size and SHA-256 checksum, the config and
mapping files' checksums, the code's version and git commit, and the library versions. It holds no
cell values. The last line of the run's log says
whether the report needs attention; read the report when it does. Each run's log is also saved
in `logs/` (set by `log_folder` in `config.toml`; the newest 20 are kept). Set
`HWW_LOG_FORMAT=json` for one JSON object per line instead, as Cloud Logging expects.
The dashboard picks up new tables automatically after `wrangle.py` runs again (refresh the browser).

`[output] target` in `config.toml` chooses where the tables go: `"folder"` (CSV files in
`output/`, the default) or `"bigquery"` (tables in a BigQuery dataset, all replaced at once, with
the report and an append-only `runs` table of run records). Any config value can use `${NAME}`
for an environment variable, as in py-common, so a config used in GCP can take its paths and
names from the job's environment.

`python wrangle.py other.toml` uses another config, and
`python -m hww_dashboard.wrangle [config.toml]` does the same as
`python wrangle.py`. To show the tables in another folder, set the
`HWW_OUTPUT` environment variable to it before starting the dashboard.

### Ingesting with py-common first

The workbooks can also go through py-common, the shared ingestion
library, before `wrangle.py` and the dashboard use them:

```
workbooks dropped in landing/<folder>/   (or a GCS bucket in GCP)
  -> python ingest.py     py-common checks each workbook against its
                          contract and loads each sheet into a raw
                          JSON table (hww_signups, hww_survey,
                          hww_was, hww_peer)
  -> python wrangle.py    with [landed] read = true: reads the newest
                          load of each table instead of the workbooks
  -> streamlit run dashboard.py
```

Try it on the dummy files in the folder above this one. In
PowerShell:

```powershell
pip install -e ".[landing]" -c constraints.txt
Copy-Item config.toml landed.local.toml   # then set read = true under [landed]
python ingest.py landed.local.toml --stage ..
python wrangle.py landed.local.toml
streamlit run dashboard.py
```

In Cloud Shell (bash), use `cp config.toml landed.local.toml` for the
copy; the other lines are the same.

`--stage ..` copies the three workbooks into their landing folders, as
if they had been dropped there: the monitoring workbook into
`landing/signups/`, where it loads both the signups and the survey
tables, and the others into `landing/was/` and `landing/peer/`. Without it, `ingest.py` loads whatever is
in those folders; a file it has already loaded is skipped.

The contracts are in `src/hww_dashboard/landing.py`, one per
workbook. Each sheet lists the columns `wrangle.py` uses, with their
types, and the columns to leave out (personal and unused ones), which
are never loaded. A workbook with a column the contract doesn't know,
a listed column missing, or a value of the wrong type is quarantined
(copied to `store/quarantine/`) and nothing from it loads, on any of
its sheets; `ingest.py` then exits with code 1 and says why. A bad
Survey info sheet therefore stops Account signups loading from the
same upload too, so the two always come from the same upload.
"Number of sites" on Account signups and Survey info mixes numbers and
text, so it is loaded as text without a type check. Its heading is
still required, and extra columns on those sheets are rejected just as
they are for the other sources.

A source with `file_pattern` ingests only the newest matching workbook,
using the date in its filename, then its modification time and filename
to break ties. Excel lock files and nonmatching workbooks are ignored.
Readers apply the configured filename selection to committed history,
so an older export loaded later cannot replace a newer dated export.

`allow_empty = true` in a source's section also applies to
ingestion. The readers select from audit records, including successful
zero-row loads, rather than inferring the latest upload from data rows.
This prevents an empty snapshot from reviving an older nonempty one.

Each raw table row holds the loaded columns as a JSON payload, with
the file, its version, the sheet and the Excel row number it came
from (py-common's `docs/RAW_TABLE_LAYOUT.md`). Rows are only ever
inserted; readers take the newest committed load. Locally, each load
of a table is two files in `landed/<table>/`: its rows (`.ndjson`) and
its audit record (`.audit.json`). The audit record is written last, in
one atomic file replacement, and is what commits the load: rows
without one are never read, and the next run loads them again.

Column exclusions apply to the raw tables, not to archived originals.
py-common stores complete source workbooks in `store/raw/` and copies
rejected workbooks to `store/quarantine/`; those copies retain personal
and unused columns and need the same access and retention controls as
the landing files. The raw tables retain prior committed uploads too.

The tables built this way are identical to those built from the
workbooks directly (`tests/test_landing.py` checks this against the
golden snapshot). `[landed] target = "gcp"` uses a landing bucket, a
store bucket and a BigQuery dataset instead of the local folders; see
[docs/gcp_ingestion.md](docs/gcp_ingestion.md) for every step. That route is unit-tested against a fake
BigQuery client but has not been run against a real project yet.
`landing/`, `store/` and `landed/` hold copies of the data, so they are
not kept in git.

Operator instructions: [docs/runbook.md](docs/runbook.md).
GCP deployment and acceptance checks: [docs/gcp.md](docs/gcp.md).
Ingesting on GCP with py-common, start to finish: [docs/gcp_ingestion.md](docs/gcp_ingestion.md).

How it all works, step by step: [docs/pipeline_guide.md](docs/pipeline_guide.md).

## Project layout

| Path | What it is |
|---|---|
| `wrangle.py`, `dashboard.py` | The two commands: small launchers that call the package. |
| `src/hww_dashboard/wrangle.py` | The pipeline: reads, cleans and links the inputs, writes the tables and the report. |
| `src/hww_dashboard/dashboard_data.py` | Every sum the dashboard shows. No Streamlit code, so it is tested on its own. |
| `src/hww_dashboard/dashboard.py` | The Streamlit pages, charts and branding. It only draws. |
| `config.toml`, `mappings/` | Settings and lookup tables (below). |
| `output/` | The tables `wrangle.py` writes. Not kept in git: with real data it holds organisation names and survey answers. |
| `tests/` | Tests grouped by the function under test, the golden-output check and page smoke tests. |
| `tests/data/` | Synthetic input workbooks and the frozen config the tests use ([README](tests/data/README.md)). |
| `docs/` | The pipeline guide, the GCP guides ([gcp.md](docs/gcp.md), [gcp_ingestion.md](docs/gcp_ingestion.md)), the architecture notes, the rule register ([rules.md](docs/rules.md)), the identifiers, the output contract and the data protection notes ([data_protection.md](docs/data_protection.md), for the DPIA). |
| `CONTRIBUTING.md` | How to set up, check and change the project. |
| `DECISIONS_en.md` | The decision log: what was decided, when and why. |

## Checks for developers

```
pip install -r requirements-dev.txt -c constraints.txt
pre-commit install
black --check .
ruff check .
mypy
python -m pytest -W error
```

Settings are in `pyproject.toml`: PEP 8 with 79-character lines, the same
Black, Ruff and mypy versions as py-common, Google-style docstrings
(checked by Ruff) and mypy in strict mode. `pre-commit install` makes git
run Black, Ruff, mypy, a secrets scan and a check that no real data is
being committed before every commit (`.pre-commit-config.yaml`).

GitHub Actions (`.github/workflows/tests.yml`) runs the checks with the
pinned versions on Python 3.11, 3.12 and 3.13 on Linux and on Windows,
audits the dependencies with pip-audit, and fails if test coverage drops
below 90%. Two more jobs run the tests with the oldest and the newest
versions `pyproject.toml` allows.

The tests are self-contained: they read the synthetic workbooks in
`tests/data/inputs/` through `tests/data/config.toml`, never the real
inputs, and treat 12:00 on 10 October 2026 as now, so they give the
same result on any day. `tests/test_golden.py` compares every output
CSV and the data quality report with a saved copy in `tests/golden/`,
so a tidy-up that changes any output fails. The tests never rewrite
that copy. When an output change has been agreed, run
`python scripts/refresh_golden.py`, check every line of
`git diff tests/golden`, and commit the copy with the change
([CONTRIBUTING.md](CONTRIBUTING.md#golden-files)).

## Dashboard pages

| Page | Mockup | Notes |
|---|---|---|
| Home | - | Headline numbers and the latest data quality report. |
| Employer view | page 2 | Pick one or more employers. Dates after today (booked WAS sessions) are not counted as engagement yet. |
| Engagement | page 3 | Monthly counts and running total. Shown as two panels sharing the month axis rather than one chart with two y-axes, so the two scales can't be misread against each other. |
| Events | page 4 | Charts `fact_event.csv` once it has rows; until then shows a message. |
| Survey findings | page 1 | % of respondents choosing each answer (Figure 13 style), with filters. Answers nobody chose show as 0%. |

All filters start with everything selected. Events and survey responses with no linked employer count as "Unknown" for sector, industry, size and sites.
A warning appears when a chart rests on fewer than 10 respondents or records (`SMALL_N` at the top of `src/hww_dashboard/dashboard.py`).
Every chart has a "Show data table" box with the numbers behind it.

To show the HWW logo instead of the text name, save it as `assets/logo.png` in this folder.
`hww_dashboard.dashboard_data` does all the sums (and is what the unit tests check); `hww_dashboard.dashboard` only draws.

## Using the real data

1. Put the real files in the input folder and change the file names in `config.toml`.
2. Run `python wrangle.py` and read **Needs attention** at the top of
   `output/data_quality_report.md`. Each line says what was found and what to do, for example:
   - values not in the mapping files - add them to the CSVs in `mappings/`;
   - new or missing survey columns - the form changed; update `mappings/survey_columns.csv`;
   - answers not in `survey_answers.csv` - add the option, or a Welsh translation to
     `survey_answer_translations.csv`.
3. Run again until Needs attention says `None.`, then `python -m pytest`.

[docs/runbook.md](docs/runbook.md) covers exit codes, recovery and support.

The tests never read the real data, so they keep passing whatever `config.toml` points at.
`output/` is ignored by git, so real tables can't be committed by accident.

## Mappings (`mappings/`)

| File | What it does |
|---|---|
| `sector.csv`, `industry.csv`, `size_band.csv`, `sites_band.csv` | Map every label used in any file to one agreed list. Matching ignores case and spaces. |
| `org_overrides.csv` | Force two spellings to be the same organisation: `raw_name,canonical_name`. |
| `agreed_values.csv` | The agreed values of each band, topic and duration, in the order people expect them. Every `agreed_value` in the files above must be listed here, so a typo stops the run instead of creating a new band. |
| `was_duration.csv`, `was_topic.csv` | Tidy WAS session durations and topics. |
| `survey_columns.csv` | What each column on Survey info is (question, tick-box option, employer field, or `drop`). Repeated headers are numbered like pandas: `Other`, `Other.1`, ..., `Other (more info)`, `Other (more info).1`, ... |
| `survey_questions.csv` | Question id, full text, short name for the picker, single or multi. |
| `survey_answers.csv` | Answer options per question, with short chart labels and sort order. |
| `survey_answer_translations.csv` | Welsh answers -> English answers. |

**Editing in Excel:** Excel turns values like `2-5` into dates. Edit these files in a text editor,
or import them into Excel as Text columns.

## Output tables

Each table's columns, types and which may be empty are fixed by a schema
file in `src/hww_dashboard/schema/`, and checked before it is written:
see [docs/output_contract.md](docs/output_contract.md).

| Table | One row per | Used on |
|---|---|---|
| `dim_employer` | organisation (duplicates merged) | all pages: filters and employer picker |
| `fact_signup` | sign-up row on Account signups (a "user") | not shown yet (page 2 Users counts `account_signup` in `fact_engagement`) |
| `fact_engagement` | event: `account_signup`, `survey_completed`, `was_request`, `was_session_held`, `was_completed`, `peer_mentoring_interest` | pages 2 and 3 |
| `dim_survey_response` | survey response, with its own sector/size/etc. | page 1 filters |
| `fact_survey_answer` | ticked option or single answer | page 1 chart |
| `question_catalogue` | question and answer option | page 1 picker and labels |
| `fact_was_session` | WAS session (sessions 1-3 unpivoted) | not shown yet |
| `fact_was_session_topic` | WAS session topic | not shown yet |
| `fact_event` | event action (empty for now) | page 4 |
| `badges` | employer badge (empty for now) | page 2 |
| `dim_date` | day, with month and April–March financial year | not shown yet (the date filters use each table's own dates) |

How each key is made, and which survive a new upload, is in [docs/identifiers.md](docs/identifiers.md).
Keys: `employer_id` links everything to `dim_employer`; `date` links to `dim_date`;
`response_id` links the survey tables; `answer_id` links `fact_survey_answer` to `question_catalogue`.

Survey percentage (Figure 13) = respondents who chose the answer ÷ respondents who gave any answer
to that question (distinct `response_id` in `fact_survey_answer` for that `question_id`).

## Readiness and release status

See [CHANGELOG.md](CHANGELOG.md) for 0.2.0 and
[docs/readiness.md](docs/readiness.md) for the RAP assessment and remaining
cloud acceptance, DPIA and human-review gates. Code is MIT licensed
([LICENSE](LICENSE)).
