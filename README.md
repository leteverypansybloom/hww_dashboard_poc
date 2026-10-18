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
pip install -r requirements.txt
```

(On macOS or Linux, activate with `source .venv/bin/activate`.)
`requirements.txt` installs the package, in editable mode, with the
dependencies listed in `pyproject.toml`. For the developer tools, install
`requirements-dev.txt` instead (the same as `pip install -e ".[dev]"`).

## Run

Run these from this folder (the dashboard's colours are in `.streamlit/config.toml`, which Streamlit only finds from here).

```
python wrangle.py
streamlit run dashboard.py
python -m pytest
```

Inputs are read from the folder above this one (set in `config.toml`).
The survey export is found by `file_pattern`: drop a new download in the input folder and the
newest one (by the date in its name) is used. The other files are named exactly.
If a file, sheet, column, mapping file or setting is missing, `wrangle.py` stops with a message
saying which one (exit code 1) before writing anything.
Tables and `data_quality_report.md` are written to `output/`. Read the report after every run.
The dashboard picks up new tables automatically after `wrangle.py` runs again (refresh the browser).

`python wrangle.py other.toml` uses another config, and
`python -m hww_dashboard.wrangle [config.toml]` does the same as
`python wrangle.py`. To show the tables in another folder, set the
`HWW_OUTPUT` environment variable to it before starting the dashboard.

How it all works, step by step: [docs/pipeline_guide.md](docs/pipeline_guide.md).

## Project layout

| Path | What it is |
|---|---|
| `wrangle.py`, `dashboard.py` | The two commands: small launchers that call the package. |
| `src/hww_dashboard/wrangle.py` | The pipeline: reads, cleans and links the inputs, writes the tables and the report. |
| `src/hww_dashboard/dashboard_data.py` | Every sum the dashboard shows. No Streamlit code, so it is tested on its own. |
| `src/hww_dashboard/dashboard.py` | The Streamlit pages, charts and branding. It only draws. |
| `config.toml`, `mappings/` | Settings and lookup tables (below). |
| `output/` | The tables `wrangle.py` writes (dummy data for now). |
| `tests/` | Tests grouped by the function under test, the golden-output check and page smoke tests. |
| `tests/data/` | Synthetic input workbooks and the frozen config the tests use ([README](tests/data/README.md)). |
| `docs/` | The pipeline guide and the architecture notes. |
| `CONTRIBUTING.md`, `AGENTS.md` | How to set up, check and change the project, for people and for coding agents. |
| `DECISIONS_en.md` | The decision log: what was decided, when and why. |

## Checks for developers

```
pip install -r requirements-dev.txt
black --check .
ruff check .
mypy
python -m pytest
```

Settings are in `pyproject.toml`: PEP 8 with 79-character lines, the same
Black, Ruff and mypy versions as py-common, Google-style docstrings
(checked by Ruff) and mypy in strict mode. GitHub Actions runs the same
four checks on Python 3.11, 3.12 and 3.13
(`.github/workflows/tests.yml`).

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
| Home | – | Headline numbers and the latest data quality report. |
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
2. Run `python wrangle.py` and read `output/data_quality_report.md`:
   - **Unmapped values** – add them to the CSVs in `mappings/`.
   - **Survey checks** – new or missing survey columns mean the form changed; update `mappings/survey_columns.csv`.
   - **Answer not in survey_answers.csv** – add the option, or a Welsh translation to `survey_answer_translations.csv`.
3. Run again until the report is clean, then `python -m pytest`.

The tests never read the real data, so they keep passing whatever `config.toml` points at.
Before the real files arrive, add `output/` to `.gitignore`: with real data its tables hold
organisation names and survey answers.

## Mappings (`mappings/`)

| File | What it does |
|---|---|
| `sector.csv`, `industry.csv`, `size_band.csv`, `sites_band.csv` | Map every label used in any file to one agreed list. Matching ignores case and spaces. |
| `org_overrides.csv` | Force two spellings to be the same organisation: `raw_name,canonical_name`. |
| `was_duration.csv`, `was_topic.csv` | Tidy WAS session durations and topics. |
| `survey_columns.csv` | What each survey export column is (question, tick-box option, employer field, or `drop`). Repeated headers are numbered like pandas: `Other`, `Other.1`, ... |
| `survey_questions.csv` | Question id, full text, short name for the picker, single or multi. |
| `survey_answers.csv` | Answer options per question, with short chart labels and sort order. |
| `survey_answer_translations.csv` | Welsh answers -> English answers. |

**Editing in Excel:** Excel turns values like `2-5` into dates. Edit these files in a text editor,
or import them into Excel as Text columns.

## Output tables

| Table | One row per | Used on |
|---|---|---|
| `dim_employer` | organisation (duplicates merged) | all pages: filters and employer picker |
| `fact_signup` | sign-up row on Account signups (a "user") | page 2 Users |
| `fact_engagement` | event: `account_signup`, `survey_completed`, `was_request`, `was_session_held`, `was_completed`, `peer_mentoring_interest` | pages 2 and 3 |
| `dim_survey_response` | survey response, with its own sector/size/etc. | page 1 filters |
| `fact_survey_answer` | ticked option or single answer | page 1 chart |
| `question_catalogue` | question and answer option | page 1 picker and labels |
| `fact_was_session` | WAS session (sessions 1-3 unpivoted) | WAS detail |
| `fact_was_session_topic` | WAS session topic | WAS detail |
| `fact_event` | event action (empty for now) | page 4 |
| `badges` | employer badge (empty for now) | page 2 |
| `dim_date` | day, with month and April–March financial year | all date filters |

Keys: `employer_id` links everything to `dim_employer`; `date` links to `dim_date`;
`response_id` links the survey tables; `answer_id` links `fact_survey_answer` to `question_catalogue`.

Survey percentage (Figure 13) = respondents who chose the answer ÷ respondents who gave any answer
to that question (distinct `response_id` in `fact_survey_answer` for that `question_id`).
