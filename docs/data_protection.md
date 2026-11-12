# Data protection notes

*For whoever writes the DPIA, and anyone deciding who may see the
pipeline's tables. It describes what the code does; the decisions it
lists at the end belong to the data owner and the DPO.*

## Personal data in the outputs

The DPIA approves personal data in the reporting (gold) tables
(`DECISIONS_en.md`, 2026-11-12). The pipeline therefore has no check
that stops a run, or hides a value, because it looks like an email
address, a phone number or a link. What reaches an output is decided
by the contracts, the mappings and each table's schema, and each
column added to an output should be one the DPIA covers.

## What the inputs hold

The three workbooks hold more than the pipeline uses:

- **Personal columns.** Names, email addresses (among them `Email
  address` on Survey info, the respondent's own address), job roles,
  contact details, accessibility requirements and adviser names.
- **Organisation names.** For a sole trader or a very small employer,
  the name can identify a person.
- **Free text.** The survey's "Other (more info)" boxes and "What parts
  could be improved?", the job role on Account signups, and the
  "Completed survey?" and "Requested WAS?" cells, which staff type by
  hand.

## What the pipeline reads

Each sheet is read whole into memory, then only the columns named in
`config.toml` and `mappings/survey_columns.csv` are used.

With `[landed] read = true`, the separate py-common ingestion job checks
each workbook and loads only the contract's listed columns into raw
tables, as a JSON payload per row with the file, version and Excel row
it came from. Excluded columns are not loaded. They are the columns no
table uses yet, personal ones among them: the contact, job role,
accessibility and adviser columns of the WAS database, the name, job
role, email and adviser columns of the peer database, and, on Survey
info, `Email address`, `Month`, "What parts could be improved?" and an
empty column (the `drop` role). A column is loaded once a contract
lists it. Unknown signup and survey columns are rejected; the
mixed-value Number of sites exception applies only to that named column
on each sheet. Ingestion archives the complete original workbook in its
object store, including excluded columns. Rejected files are retained
in raw and quarantine storage.

## What it writes

Only the columns in each table's schema are written
(`docs/output_contract.md`). What could identify someone:

| Where | What | Notes |
|---|---|---|
| `dim_employer.employer_name` | organisation names | can identify a sole trader |
| every `employer_id` | a hash of the organisation name | pseudonymous, not anonymous: anyone with a list of names can recompute it |
| `fact_signup` | one row per user: employer, sign-up month, flags | job roles and the flag cells' text are not written, as no table uses them yet |
| `fact_was_session`, `fact_was_session_topic` | session topics and durations | a value missing from the mapping files is kept as typed |
| `survey_other_text` | free text from "Other (more info)" boxes | written on every run, as typed |
| `data_quality_report.md` | organisation names, and raw values that didn't map or couldn't be read | shown in full; the dashboard's Home page shows the whole report |

## Logs

Log lines name files, sheets, columns and counts, never cell values.
On a laptop each run's log is saved in `logs/`, and only the newest 20
are kept. An unexpected error's traceback goes in that file and could
quote a value, so git ignores `logs/` like `output/`. With
`HWW_LOG_FORMAT=json`, as in GCP, an error is logged by type and code
location only, without its message.

## Run records

Each published set of outputs comes with `run_record.json`: the input
files' names, sizes, times and checksums, the config's and mapping
files' checksums, row counts, and the code and library versions. It
holds no cell values, so it can be kept and shared like py-common's
audit records.

## Where the data is

- **Laptops**: the input workbooks (outside the repository), `output/`
  and `logs/`. git ignores both folders, and a pre-commit hook refuses
  workbooks, stray CSV files and anything under `output/`.
- **Optional py-common ingestion**: `landing/` contains source
  workbooks, `store/` retains originals, rejected copies and processed
  files (the loaded rows as NDJSON), and `landed/` retains every
  committed load of the raw tables. In GCP the configured buckets
  and landed BigQuery dataset serve those roles. Original workbooks
  retain excluded personal columns. Restrict access accordingly; git
  ignores the local folders but does not enforce storage access.
- **The repository** holds only synthetic data: the test workbooks use
  reserved values (`example.org`, `192.0.2.x`), and a test fails if a
  real-looking email address, IP address or link appears in them.
  Real organisation overrides belong in a private file configured by
  `[paths] org_overrides_file`, or a private reference table for
  Dataform.
  The committed override CSV remains an empty template. The repositories
  are public; no production values belong in Git or generated JavaScript.
- **BigQuery** (in GCP, with `[output] target = "bigquery"`): the
  tables and the report are in one interim dataset, which only the
  pipeline's service account, and whoever the DPIA allows, should be
  able to read. Each run replaces them; the `runs` table keeps every
  run's record (no cell values). BigQuery keeps replaced or deleted
  rows for up to 7 days (time travel), then 7 more days (fail-safe),
  and the staging tables of a run that died expire after a day.
- **The dashboard** has no sign-in. It must not be reachable beyond the
  laptop it runs on while it shows real data.

## How long it is kept

Each run replaces the output tables and the report. The previous set is
deleted once the new one is in place, unless restoring it failed (it is
then kept in a `.hww-*` folder next to the output, for recovery). Run
logs: the newest 20.

py-common ingestion retains original workbooks and every previous
upload's rows in the raw tables; replacing dashboard outputs does not
remove them. The data owner must set retention and deletion rules for
landing, raw, quarantine, processed and raw-table storage separately
(py-common's `docs/RUNBOOK.md` says how to remove one upload
completely).

## Decisions for the DPIA

- Retention periods for inputs, outputs and logs, on laptops and in GCP.
- Who may see the output tables and the report, and through what
  (dashboard, BigQuery, Power BI).
- Which personal columns each new table or column may carry, as the
  DPIA approves them.
- Where `mappings/org_overrides.csv` lives once it holds real names.

## Dataform and production policy

Silver includes retained source values and restricted data-quality output.
Gold contains reporting data, personal data among it; assertion results
and acceptance differences can also expose retained rows. Apply the
approved access and retention policy to silver, gold, assertions, job
history and logs as well as raw. See [production operation](production.md) for the per-source
correction and erasure procedure, production roles, and decisions awaiting
the data owner and IG lead. No retention period is approved by the code.
