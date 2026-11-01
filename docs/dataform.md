# The Dataform layer

*For whoever sets up, runs and changes the HWW models in GCP Dataform.*

The production route for HWW data is:

```
workbook uploaded   ->  py-common (ingestion)  ->  Dataform               ->  Power BI
to the landing          one raw JSON table         bronze -> silver -> gold    (reports)
bucket                  per sheet (bronze)         the reporting tables
```

The models in [`dataform/`](../dataform/) are the Dataform step. They
take over the work `src/hww_dashboard/wrangle.py` does today, the
cleaning and modelling after ingestion, and build the same tables:

- **Bronze**: py-common's raw tables in `hww_landed`, as
  `docs/gcp_ingestion.md` sets them up. Dataform only reads them.
- **Silver** (`hww_silver`): the mappings as reference tables, the
  load each source reads, one cleaned and typed row per source row,
  and a view of data quality issues.
- **Gold** (`hww_gold`): the twelve tables of
  [output_contract.md](output_contract.md), with the same columns,
  types and identifiers. Power BI reads only these.

> **Status.** The models compile, and every compiled query passes a
> BigQuery SQL parser. They haven't run on BigQuery yet. Treat the
> first run in a development project as a test, and check the results
> against the Python pipeline (step 9) before anyone reports from them.

`dataform/README.md` lists the files; [rules.md](rules.md) names the
model behind each rule.

## How it is built, and why

**One rule, one place.** Each cleaning rule (tidying text, reading
dates, name keys, employer ids, the sign-up flags) is one function in
`dataform/includes/hww.js` that writes the SQL, used by every model
that needs it. Each function names the rule it implements.

**The mapping files stay the source.** Dataform can't read CSV files,
so `dataform/scripts/build_reference_data.js` copies `mappings/*.csv`,
the schema files and `tests/data/identifier_cases.json` into
`dataform/includes/reference_data.js`, and the `ref_*` tables are
built from it. Keep editing the CSV files, then rebuild that file and
commit both. CI fails if they disagree.

**Each source reads one load.** `raw_latest_loads` takes, for each raw
table, the newest load of its agreed file name from py-common's
`audit` table, as `landed.py` does. An upload with no rows counts as a
load, so it is never mistaken for the upload before it.

**Stops keep the last good tables.** The checks that stop
`wrangle.py` (a missing or incomplete load, an empty source, a broken
mapping file, a sign-up month that isn't a date, an identifier rule
that disagrees with Python, repeated ids) are Dataform assertions. The
gold tables wait for all of them, so if one fails no gold table is
rebuilt and readers keep the previous run's tables.

**Warnings are a view.** What `data_quality_report.md` lists
(unmapped values, unreadable flags, new survey columns or answers,
undated sessions, a large drop in rows) is in
`hww_silver.data_quality_issues`, one row per kind of issue.
`needs_attention` marks the ones the report's "Needs attention" block
lists.

**Settings live in `workflow_settings.yaml`.** The settings
`config.toml` holds for the modelling (`completed_rule`,
`keep_other_free_text`, `source_priority`, `max_row_drop`,
`allow_empty` and each workbook's file name) are Dataform variables
with the same values. The WAS session columns (`[[was.sessions]]`)
and the payload keys of each sheet are in `includes/hww.js`.

**A new gold dataset.** Until the gold tables match, the Python
pipeline keeps loading the interim `hww_reporting` dataset. The gold
tables have the same names and columns, so a report moves over by
changing the dataset name (step 11).

## Set-up

Names follow `docs/gcp_ingestion.md`: an app project for what runs, a
data project for what holds data. Replace `<app-project>`,
`<data-project>` and the names below with yours.

| Step | Who |
|---|---|
| 1: Publish the Dataform folder as a branch | You |
| 2, 3: Datasets, service account and roles | Admin |
| 4, 5: GitHub token and the Dataform repository | Admin, or you with the roles |
| 6 to 11 | You |

### 1. Publish the Dataform folder as a branch

GCP Dataform reads `workflow_settings.yaml` from the root of the Git
repository it is connected to, and here it is in `dataform/`. So
publish that folder as a branch of this repository whose root is the
folder:

```bash
git push origin "$(git subtree split --prefix dataform main):refs/heads/dataform"
```

Run it again after each change to `dataform/` reaches `main`. The
`dataform` branch only ever holds copies of `main`'s folder: make
changes on `main` (by pull request, as for any other change), never in
the branch or in a Dataform workspace commit.

A separate repository holding only the Dataform project works the same
way, if your team prefers one: push the same split to its `main`.

### 2. Create the datasets

In the data project, in the same location as `hww_landed`:

```bash
for DATASET in hww_silver hww_gold hww_assertions; do
  bq --location=europe-west2 mk --dataset "<data-project>:$DATASET"
done
```

For a development environment in the same project, use a suffix
(`hww_silver_dev` and so on) and set it in step 8.

### 3. Create the service account and give it access

The workflows run as their own service account, in the app project:

```bash
gcloud iam service-accounts create hww-dataform \
  --project=<app-project> --display-name="HWW Dataform"
```

Give it, on the data project:

| Role | On | Why |
|---|---|---|
| `roles/bigquery.jobUser` | Data project (and the app project) | Run queries |
| `roles/bigquery.dataViewer` | `hww_landed` dataset | Read the raw tables and `audit` |
| `roles/bigquery.dataEditor` | `hww_silver`, `hww_gold`, `hww_assertions` datasets | Create and replace the tables and views |

Dataform's own service agent,
`service-<app-project-number>@gcp-sa-dataform.iam.gserviceaccount.com`,
needs `roles/iam.serviceAccountTokenCreator` on `hww-dataform`, to run
workflows as it. Whoever creates the workflow configuration (step 8)
needs `roles/iam.serviceAccountUser` on it.

Report readers need only `roles/bigquery.dataViewer` on `hww_gold`
(and `roles/bigquery.jobUser` where they run queries). Nobody who reads
reports needs the raw or silver datasets.

### 4. Store a GitHub token

Create a fine-grained personal access token for this repository with
read and write access to its contents (Dataform can push from
workspaces; read access is enough if nobody will). Store it in Secret
Manager in the app project:

```bash
printf '%s' "<token>" | gcloud secrets create hww-dataform-github-token \
  --project=<app-project> --data-file=-
gcloud secrets add-iam-policy-binding hww-dataform-github-token \
  --project=<app-project> \
  --member="serviceAccount:service-<app-project-number>@gcp-sa-dataform.iam.gserviceaccount.com" \
  --role=roles/secretmanager.secretAccessor
```

### 5. Create the Dataform repository

In the console, in the app project: **Dataform > Create repository**.

- Repository ID `hww`, region `europe-west2`.
- Service account: `hww-dataform@<app-project>.iam.gserviceaccount.com`.

Then open it, **Settings > Connect with Git**:

- Remote URL: this repository's HTTPS URL.
- Default branch: `dataform` (step 1).
- Secret: the one created in step 4.

### 6. Set the project and settings

`workflow_settings.yaml` says `defaultProject: your-data-project`.
Either change it on `main` to the data project's id, or leave it and
set the project per environment in the release configuration (step 8),
which is what lets one branch serve development and production.

The variables under `vars:` mirror `config.toml`. Change them together:
`signups_file`, `was_file` and `peer_file` must be the agreed file
names that py-common's contracts check, so with the real workbooks
they change from the dummy names.

### 7. Run it once in a development workspace

**Development workspaces > Create development workspace**, open it and
pull from the default branch. The **Compiled graph** shows every
action; there should be no compilation errors. Then **Start execution
> All actions**, with the development project (or suffix) set in
**Workspace compilation overrides**.

If an assertion fails, open it in BigQuery (`hww_assertions.<name>`):
each row is one problem, saying what and where.

### 8. Schedule it

**Releases & scheduling > Create release configuration**:

- Release ID `production`, Git commitish `dataform`.
- Frequency: daily, before the workflow below runs.
- Compilation overrides: the data project's id, and for development a
  schema suffix such as `dev`. Variables can be overridden here too.

**Create workflow configuration**:

- Release configuration `production`, service account `hww-dataform`.
- Schedule `0 7 * * *` in `Europe/London`: an hour after the daily
  ingestion job (`hww-daily-0600`) starts, so the day's uploads are
  loaded.
- Actions: all actions.

Running Dataform straight after ingestion, instead of at a fixed time,
needs the ingestion job (or a Cloud Workflow around it) to call the
Dataform API when it finishes. That is a later improvement; the fixed
time is enough for monthly and weekly uploads.

### 9. Check it against the Python pipeline

The Python pipeline is the specification, and two sets of expected
tables come with it ([output_contract.md](output_contract.md),
"Comparing another implementation"). Use a development project or
suffix for both.

**The golden snapshot.** Land the synthetic workbooks in
`tests/data/inputs/` with py-common, as `docs/gcp_ingestion.md` steps
1 to 4 describe. Load the expected tables:

```bash
bq --location=europe-west2 mk --dataset "<data-project>:hww_expected"
for TABLE in dim_employer fact_signup fact_engagement dim_survey_response \
    fact_survey_answer question_catalogue fact_was_session \
    fact_was_session_topic fact_event badges dim_date; do
  bq load --replace --source_format=CSV --skip_leading_rows=1 \
    "<data-project>:hww_expected.$TABLE" "tests/golden/$TABLE.csv" \
    "src/hww_dashboard/schema/$TABLE.json"
done
```

Then run all actions with the variable `expected_dataset` set to
`hww_expected` (in the workspace's compilation overrides). Every
`acceptance_<table>` assertion must pass; a failing one lists the rows
that differ, as JSON.

**The hand-worked scenarios.** On a scratch branch, add the scenario
override to `mappings/org_overrides.csv` (`Delta Trading` to
`Gamma Group`, as `tests/test_scenarios.py` does) and rebuild the
reference data. Write the workbooks with
`python tests/scenarios/workbooks.py scenario-inputs`, land them in a
clean development dataset, and load `tests/scenarios/expected/*.csv`
as above (not the two `was_completed_*` files). Run with
`expected_dataset` and with `expected_tables` set to the tables that
have expected files. To check the other two completion rules, set
`completed_rule` and compare the `was_completed` rows of
`fact_engagement` with `was_completed_<rule>.csv`.

When both pass, record it in `DECISIONS_en.md`.

### 10. Alert on failures

Each workflow run writes a log entry when it ends. In **Logging >
Logs Explorer**, find the entry of a failed run (filter on the
resource type "Dataform Repository"; break a mapping file on purpose
in development to make one) and create a log-based alert from it,
sent to the same channel as the ingestion job's alerts.

Also look at `hww_silver.data_quality_issues` after each upload, or
build a report page on it:

```sql
SELECT * FROM `<data-project>.hww_silver.data_quality_issues`
WHERE needs_attention
ORDER BY section, source
```

### 11. Move the reports over

Once step 9 passes and a few scheduled runs have matched the Python
pipeline's `hww_reporting` tables (compare them with the acceptance
assertions, `expected_dataset = hww_reporting`), point Power BI at
`hww_gold`, stop the Python pipeline's BigQuery output and remove its
access to `hww_reporting`.

## Changing things

| Change | Do |
|---|---|
| A mapping (band, topic, translation, override, survey column) | Edit `mappings/*.csv`, run `node scripts/build_reference_data.js` in `dataform/`, commit both, publish (step 1). |
| A workbook's columns | Change the contract in `src/hww_dashboard/landing.py` and the payload keys in `dataform/includes/hww.js` together: the models read the keys py-common loads. |
| A setting in `config.toml` | Change the same variable in `workflow_settings.yaml`. |
| An output column | An output change (`CONTRIBUTING.md`): change `COLUMNS` in `wrangle.py`, the schema file and the gold model together, then rebuild the reference data. `gold_<table>_contract` fails until they agree. |

## Where it differs from the Python pipeline

Known differences, none of which changes a gold table built from the
same inputs:

- **Not one transaction (R82).** Each gold table is replaced on its
  own. The stops run first, so bad inputs never reach gold, but a
  failure part-way through a run (a quota, a bug) can leave some gold
  tables from this run and some from the last. Running the workflow
  again fixes it. The output contract checks (R80, R81) run after the
  tables are built, so a failure there means fixing the model before
  anyone reads the tables.
- **No run record table (R83).** Dataform keeps each run's history,
  with its logs and compiled SQL, in the repository.
- **Row drop (R84)** compares the selected upload with the previous
  upload of the same file in py-common's audit table, instead of with
  the last published run.
- **File names (R02).** Only the agreed file name is read; there is no
  `file_pattern`. py-common's contracts already require one name per
  workbook.
- **Dates (R11).** Only ISO dates are read, because py-common's
  contracts refuse a date column holding anything else; the
  day-first text and Excel serial numbers `to_date` also reads never
  reach the raw tables.
- **Case folding for mappings (R12, R33).** SQL's `LOWER` stands in for
  Python's `casefold`; they differ only for a few letters such as `ß`,
  which no mapping uses. Employer keys use `NORMALIZE_AND_CASEFOLD`,
  and `assert_identifier_cases` checks them against Python's.
- **Personal columns (R05)** are enforced where they enter: py-common
  never loads a column the contracts exclude, so there is nothing for
  Dataform to check.
- **The report** is the `data_quality_issues` view, not a Markdown
  file, and "dated after today" uses today's date in Europe/London
  when the view is read.
