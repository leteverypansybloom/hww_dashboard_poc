# Output contract

*For anyone who reads the pipeline's tables, and for whoever builds the
Dataform models that will replace the pipeline.*

The pipeline writes eleven tables, or twelve when
`keep_other_free_text` is on. One schema file per table in
[`src/hww_dashboard/schema/`](../src/hww_dashboard/schema/), in
BigQuery's JSON schema format, fixes each table's columns, their order
and types, which may be empty, and what each holds. Every table is
checked against its schema before it is written, as a CSV file or a
BigQuery table. A table that doesn't fit stops the run with exit code 2,
because that is a bug in the pipeline, never a problem with the
inputs. The Dataform models should produce tables with the same
schemas.

## Tables

| Table | One row per | Key |
|---|---|---|
| `dim_employer` | organisation, with duplicate spellings merged | `employer_id` |
| `fact_signup` | row on Account signups (a user) | `signup_id` |
| `fact_engagement` | engagement event | `engagement_id` |
| `dim_survey_response` | survey response | `response_id` |
| `fact_survey_answer` | response and option chosen | `response_id`, `question_id`, `answer` |
| `survey_other_text` | free text typed into an "Other" box (only when switched on) | `response_id`, `question_id` |
| `question_catalogue` | question and answer option | `answer_id` |
| `fact_was_session` | WAS session with any detail recorded | `session_id` |
| `fact_was_session_topic` | session and topic | `session_id`, `topic` |
| `fact_event` | event action (placeholder: no source yet) | - |
| `badges` | badge awarded (placeholder: no source yet) | - |
| `dim_date` | day, in whole financial years | `date` |

How stable each key is across uploads is in
[identifiers.md](identifiers.md).

## Types and empty values

| Schema type | In a CSV file | In BigQuery |
|---|---|---|
| `STRING` | text | `STRING` |
| `DATE` | `YYYY-MM-DD` | `DATE` |
| `BOOL` | `True` or `False` | `BOOL` |
| `INT64` | a whole number | `INT64` |
| any type, empty | an empty cell | `NULL` |

- A `REQUIRED` column is never empty.
- Empty (`NULL`) means "doesn't apply" or "not recorded": no employer
  link, no session date. `Unknown` is different: it is a real band value
  meaning "no usable answer", and you can filter on it.
- Lists inside one cell, such as `survey_dates` (`2025-11-01;2026-08-01`)
  and `topics` (`Physical activity; Mental health and wellbeing`), are
  `STRING`.
- CSV files use UTF-8 and LF line endings on every system.

A schema file creates its table directly, for example:

```
bq mk --table PROJECT:DATASET.dim_employer src/hww_dashboard/schema/dim_employer.json
```

## Comparing another implementation with this one

To check Dataform's tables against this pipeline's, load the expected
tables, for example a golden file from `tests/golden/`, with the same
schema. BigQuery's CSV loader reads empty cells as `NULL` and `True` or
`False` as `BOOL`:

```
bq load --source_format=CSV --skip_leading_rows=1 \
  PROJECT:expected.dim_employer tests/golden/dim_employer.csv \
  src/hww_dashboard/schema/dim_employer.json
```

Then compare both ways, and the row counts. Each query must return no
rows:

```sql
SELECT * FROM `PROJECT.expected.dim_employer`
EXCEPT DISTINCT
SELECT * FROM `PROJECT.dataform.dim_employer`;

SELECT * FROM `PROJECT.dataform.dim_employer`
EXCEPT DISTINCT
SELECT * FROM `PROJECT.expected.dim_employer`;
```

## Changing a table

Adding, removing or retyping a column is an output change, so it needs
the project owner's approval (`CONTRIBUTING.md`). Change `COLUMNS` in
`src/hww_dashboard/wrangle.py` and the table's schema file together. A
test fails if they differ.
