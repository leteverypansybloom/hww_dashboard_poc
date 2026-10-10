# HWW dashboard

Two steps:

1. `wrangle.py` turns the HWW spreadsheets into tidy CSV tables in `output/`.
2. `dashboard.py` is a Streamlit app that draws the mockup pages from those tables.

## Run

Needs Python 3.11 or newer. Run these from this folder (the dashboard's colours are in `.streamlit/config.toml`, which Streamlit only finds from here).

```
pip install -r requirements.txt
python wrangle.py
streamlit run dashboard.py
python -m pytest
```

Inputs are read from the folder above this one (set in `config.toml`).
Tables and `data_quality_report.md` are written to `output/`. Read the report after every run.
The dashboard picks up new tables automatically after `wrangle.py` runs again (refresh the browser).

## Dashboard pages

| Page | Mockup | Notes |
|---|---|---|
| Home | – | Headline numbers and the latest data quality report. |
| Employer view | page 2 | Pick one or more employers. Dates after today (booked WAS sessions) are not counted as engagement yet. |
| Engagement | page 3 | Monthly counts and running total. Shown as two panels sharing the month axis rather than one chart with two y-axes, so the two scales can't be misread against each other. |
| Events | page 4 | Charts `fact_event.csv` once it has rows; until then shows a message. |
| Survey findings | page 1 | % of respondents choosing each answer (Figure 13 style), with filters. Answers nobody chose show as 0%. |

All filters start with everything selected. Events and survey responses with no linked employer count as "Unknown" for sector, industry, size and sites.
A warning appears when a chart rests on fewer than 10 respondents or records (`SMALL_N` at the top of `dashboard.py`).
Every chart has a "Show data table" box with the numbers behind it.

To show the HWW logo instead of the text name, save it as `assets/logo.png`.
`dashboard_data.py` does all the sums (and is what the tests check); `dashboard.py` only draws.

## Using the real data

1. Put the real files in the input folder and change the file names in `config.toml`.
2. Run `python wrangle.py` and read `output/data_quality_report.md`:
   - **Unmapped values** – add them to the CSVs in `mappings/`.
   - **Survey checks** – new or missing survey columns mean the form changed; update `mappings/survey_columns.csv`.
   - **Answer not in survey_answers.csv** – add the option, or a Welsh translation to `survey_answer_translations.csv`.
3. Run again until the report is clean, then `python -m pytest`.

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
