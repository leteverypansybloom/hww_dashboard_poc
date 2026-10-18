# Data protection notes

*For whoever writes the DPIA, and anyone deciding who may see the
pipeline's tables. It describes what the code does; the decisions it
lists at the end belong to the data owner and the DPO.*

## What the inputs hold

The four workbooks hold more than the pipeline needs. The columns
listed under `[privacy] personal_columns` in `config.toml` are the known
personal ones: names, email addresses, job roles, contact details,
accessibility requirements, adviser names, and the survey tool's user
IP address, user agent, user id, payment fields and report links. As
well:

- **Organisation names.** For a sole trader or a very small employer,
  the name can identify a person.
- **Free text.** The survey's "Other" boxes and "What parts could be
  improved?", the job role on Account signups, and the "Completed
  survey?" and "Requested WAS?" cells, which staff type by hand.

## What the pipeline reads

Each sheet is read whole into memory, then only the columns named in
`config.toml` and `mappings/survey_columns.csv` are used. Personal
columns are read into memory but never used or written.

Two checks run before any workbook is opened:

- a setting in `config.toml` that names a column on the `[privacy]`
  list stops the run;
- a survey column on that list must have the `drop` role in
  `mappings/survey_columns.csv`, or the run stops.

## What it writes

Only the columns in each table's schema are written
(`docs/output_contract.md`). What could identify someone:

| Where | What | Notes |
|---|---|---|
| `dim_employer.employer_name` | organisation names | can identify a sole trader |
| every `employer_id` | a hash of the organisation name | pseudonymous, not anonymous: anyone with a list of names can recompute it |
| `fact_signup` | one row per user: employer, sign-up month, flags | job roles and the flag cells' text are not written |
| `fact_was_session`, `fact_was_session_topic` | session topics and durations | a value missing from the mapping files is kept as typed |
| `survey_other_text` | free text from "Other" boxes | only written when `keep_other_free_text = true`; off by default |
| `data_quality_report.md` | organisation names, and raw values that didn't map or couldn't be read | the dashboard's Home page shows the whole report |

Before anything is written, every table and the report are checked for
email addresses, UK phone numbers, IPv4 addresses and web links. One
found stops the run (exit code 1), and the message names the table but
never the value. The check can't recognise people's names or postal
addresses in free text: only fixed lists of values (the mapping files)
would rule those out.

## Logs

Log lines name files, sheets, columns and counts, never cell values.
On a laptop each run's log is saved in `logs/`, and only the newest 20
are kept. An unexpected error's traceback goes in that file and could
quote a value, so git ignores `logs/` like `output/`. With
`HWW_LOG_FORMAT=json`, as in GCP, an error is logged by type and code
location only, without its message.

## Where the data is

- **Laptops**: the input workbooks (outside the repository), `output/`
  and `logs/`. git ignores both folders, and a pre-commit hook refuses
  workbooks, stray CSV files and anything under `output/`.
- **The repository** holds only synthetic data: the test workbooks use
  reserved values (`example.org`, `192.0.2.x`), and a test fails if a
  real-looking email address, IP address or link appears in them.
  Once people merge duplicate employers, `mappings/org_overrides.csv`
  will hold real organisation names; keep the repository private, or
  move that file next to the inputs before publishing the code.
- **The dashboard** has no sign-in. It must not be reachable beyond the
  laptop it runs on while it shows real data.

## How long it is kept

Each run replaces the output tables and the report. The previous set is
deleted once the new one is in place, unless restoring it failed (it is
then kept in a `.hww-*` folder next to the output, for recovery). Run
logs: the newest 20.

## Decisions for the DPIA

- Retention periods for inputs, outputs and logs, on laptops and in GCP.
- Who may see the output tables and the report, and through what
  (dashboard, BigQuery, Power BI).
- Whether `role` or the flag text should ever be output again. They
  were removed on 2026-10-18 for data minimisation.
- Whether free-text fields should be limited to fixed lists of values,
  since the contact-detail check can't recognise names.
- Where `mappings/org_overrides.csv` lives once it holds real names.
