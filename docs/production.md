# Production operation

The Python pipeline has run in a development Cloud Run job using a combined
py-common and HWW image, but that run's image revision and outputs were not
recorded. Dataform has not run on BigQuery yet. Production use needs a recorded
run of each, and code review by someone other than the author.

## Inputs

| Source | Production export | Mapping status |
| --- | --- | --- |
| Signups and survey | `HWW monitoring and reporting.xlsx` | Existing workbook contract |
| WAS | `WAS database.jsonl` | Configure after the SharePoint migration |
| Peer mentoring | `Peer Mentoring Programme Database.jsonl` | Configure after the SharePoint migration |
| Future HWW input | `HWW Database.xlsx` | Purpose and sheets are not defined; no reporting route |

WAS and peer exports contain one Graph list item per line. Keep the top-level
`id`, `createdDateTime`, `lastModifiedDateTime` and nested `fields` object as
Graph supplies them. Lookup identifiers and multi-value fields do not imply
that Graph expanded a person or lookup record. The extraction must request
the fields it needs and complete all pages before finalising an export.

Save the list column definitions alongside an export as `schema.json`.
Retrieve them from `GET /sites/{site-id}/lists/{list-id}/columns` after the
migration. This repository holds no production internal names.
The sidecar is preserved by the transfer process; ingestion does not treat
it as a source table.

A list item's `fields` also hold SharePoint's system fields and a
`<name>@odata.type` entry for each multi-choice column, and each needs
listing in `excluded_fields`. `tests/data/was_graph.toml` is a complete
example for a synthetic copy of the WAS list.

A WAS or peer export's item `id` also loads, as `SharePoint item ID`,
without any setting. It gives a row with no Participant ID a stable id.

Configure each list section with `field_map`, `metadata_map`,
`excluded_fields` and `site_time_zone`. Map canonical contract headings to internal names under
`field_map`, and canonical headings to envelope properties under
`metadata_map`. These example names describe a synthetic list:

```toml
[example.field_map]
"Organisation" = "Title"
"Reviewer" = "ReviewerLookupId"

[example.metadata_map]
"Source item" = "id"
"Modified" = "lastModifiedDateTime"
```

Use the contract's actual canonical headings when configuring WAS and peer.
Every loaded heading needs a mapping. Explicitly exclude other internal
fields. Unknown fields and missing mappings stop ingestion without printing
their values. Raw GCS copies retain the original envelope; processed JSON
contains only mapped, validated values. An `any` column retains nested or
mixed values while enforcing JSON safety limits.

`config.gcp.toml` sets `site_time_zone` to `Europe/London`. Check it against
the site's regional settings and a real export: a date entered in summer must
load as the same date. WAS topics sent as a list of choices are joined with
`topic_separator`, as a workbook export holds them. A column the migrated list
holds as a number or lookup, but the contract declares as text, quarantines the
file: change its type in `landing.py`, and check how `wrangle.py` and the
Dataform model read it.

## Proving a set-up on dummy data

The production config needs field mappings, so a new GCP set-up runs on the
dummy workbooks first. Upload them as in [GCP ingestion](gcp_ingestion.md),
then run the image with the dummy config:

```bash
gcloud run jobs update "$JOB" --project="$APP_PROJECT" --region="$REGION" \
  --command=hww-run --args=/app/config.gcp.dummy.toml
```

For Dataform, set these compilation overrides on a development release
configuration, with its own `raw_dataset`:

```text
signups_file=dummy_HWW monitoring and reporting.xlsx
was_file=dummy_was_database.xlsx
peer_file=dummy_peer_montoring.xlsx
```

## GitHub scheduling and upload events

`.github/workflows/pipeline.yml` runs daily at 06:00 UTC and supports manual
runs and a `repository_dispatch` event of type `hww-upload`. A workflow-wide
concurrency group serialises runs. The publication storage lease also
serialises the Python read-through-publish operation against Cloud Run.

Create the protected GitHub environment `hww-production`. Configure
workload identity for this repository, environment and approved branch,
then set these environment variables:

- `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_SERVICE_ACCOUNT`, `GCP_PROJECT_ID`
- `HWW_LANDING_BUCKET`, `HWW_STORE_BUCKET`, `HWW_RAW_DATASET`
- `HWW_REPORTING_DATASET`, `PY_COMMON_REF`

`PY_COMMON_REF` is the full reviewed commit of the shared-library changes.
The HWW dependency pin must be updated to that commit after the library is
committed and released. Build a new base image from that revision; the HWW
image checks that the Graph contract exists and records `HWW_GIT_COMMIT`.
The source worktree and a historic base image are not interchangeable.
Before real data is processed on GitHub, the IG lead must approve the
runner location and access model. Use an approved self-hosted runner when
the hosted runner's location is unsuitable; the workflow's runs-on setting
is the place to select it.

GCS cannot directly trigger a GitHub Actions workflow. After a successful
upload, the transfer tool or an approved event bridge must send a GitHub
repository dispatch. Do not include record values or credentials in that
payload. This repository deploys no bridge, credentials or GCP resources.

Production doesn't use this workflow: the daily job is the Cloud Run job,
whose image a Cloud Build trigger builds from `main` with
`cloudbuild.deploy.yaml` (`DECISIONS_en.md`, 2026-11-10). Keep the workflow
disabled in GitHub (**Actions > HWW pipeline > Disable workflow**), so real
data never runs on GitHub's machines. If both are ever used, already-loaded
files are skipped, and the publication lease stops them overlapping.

The Cloud Run job logs to Cloud Logging, so the log-based alerts in
py-common's `docs/GCP_SETUP.md` apply. Also set up an independent absence check for an
expected daily run. A check inside the job cannot detect a job that never
starts. The owner must approve the source freshness window; Dataform's
`max_load_age_hours` defaults to 1080 hours for monthly cumulative exports.

## Publication and recovery

Publication is held when a cumulative input has lost more rows than
`max_row_drop` permits since the last published run. Investigate the export
and its pagination. For an agreed reduction, set `allow_row_drop` to true for
one run and then restore it to false: `checks.allow_row_drop` for Python, and
the `allow_row_drop` variable for Dataform. The previous outputs and run record
remain intact while publication is held. Dataform records each published run
in `hww_gold.published_loads`, so uploading a short file a second time doesn't
pass the check.

Dataform materialises `raw_latest_loads` once per invocation and chooses the
highest numeric GCS generation. All gold tables wait for the shared checks
for load completeness, payload keys, source freshness, source keys, contact
identifiers, row counts, mappings and other contract rules. Run dependencies
with the gold selection. Gold replacement is one table at a time, which is
accepted for now: refresh Power BI only after a successful invocation, so it
never reads a part-built set. These changes need a
BigQuery execution test before cut-over.

Turning free text off rebuilds the silver and gold free-text tables empty.
It does not remove historical copies from backups, logs or earlier exports.

For rollback, select the last approved HWW commit, shared-library commit and
image digest as one release set. Restore configuration and mappings from
that set, rerun on development data, and compare with the approved outputs
before changing a production job. Do not roll back ingestion by selecting a
lower GCS generation merely because its commit time is later.

## Private mappings and access

Keep production organisation overrides out of Git and generated JavaScript.
Python accepts `privacy.org_overrides_file` outside the repository and
records its checksum. Dataform accepts `org_overrides_table` as a private
`project.dataset.table` containing `line`, `raw_name` and `canonical_name`.
The committed CSV remains an empty template.

| Principal | Production access |
| --- | --- |
| Ingestion service account | Read landing; write raw, processed, quarantine and audit; manage its lock objects; run BigQuery jobs and write the raw dataset |
| Transformation service account | Read the raw dataset and private reference tables; write silver, assertions and gold |
| Report readers | Approved reporting outputs only |
| Developers | Synthetic development resources; no default access to original production workbooks |
| Break-glass administrators | Time-limited, approved and logged access for recovery or deletion |

The administrator must verify exact roles, UK locations, log locations,
retention, read auditing and any column protections. Do not grant developers
Storage Object Viewer on the production store bucket as a setup shortcut.
The Dataform service agent needs Service Account User and Service Account
Token Creator on its custom execution account, as described in
[Google's access-control documentation](https://docs.cloud.google.com/dataform/docs/access-control).
Suffixing silver or gold datasets does not isolate raw input. Development
must use a separate project or explicitly override `raw_dataset` as well.

## Retention, correction and erasure

The data owner and IG lead must approve periods and access for landing
versions, raw and quarantine workbooks, processed copies, raw table history,
silver, gold, assertions, logs, local copies and backups. The periods are not
set yet, and nothing deletes data on a schedule.

For a correction or erasure request, identify affected source items and
exports without copying personal values into a ticket. Correct the source,
produce complete replacement exports, validate and rebuild outputs, and
check the approved result. An administrator then reviews a deletion manifest
covering all affected historic GCS generations, archived and processed copies,
raw loads, assertions, local copies and backups under the approved policy.
Record approval and verification separately from record contents.

Do not apply partition expiry indiscriminately: an old but current snapshot
can still be the latest valid load. Preserve current required snapshots until
an approved replacement is available. The IG lead must decide whether job
roles, free text and small-employer health answers may be retained.

## Known limitations

- Organisation names and some free-form values can identify people, and
  pattern checks don't make data anonymous. The DPIA has to cover them.
- Name the operators and their backup, and the expected source arrival dates.
- Signup rows and survey responses have no stable source identifier, so ids
  derived from the row or from Count can move. Ask for one, such as the survey
  tool's Entry Id on Survey info.
- Bare numeric date serials are read on the 1900 epoch. Agree a contract before
  accepting 1904 serials.
- Folder output rolls back ordinary errors, but a killed process or a reader at
  the wrong moment can see the gap during the rename.
- The dashboard reads CSV files and has no authentication. Its owners need to
  add cloud reading and access control.

## Acceptance before cut-over

Name an independent code reviewer and a data-owner approver. Record the
revision, config, mapping hashes, selected source generations and execution
result. On synthetic data, require matching schemas, key uniqueness, row
counts and complete row sets against the golden and hand-worked scenarios.
Test assertion failures before publication, privacy checks, free-text removal,
shrunken inputs, duplicate delivery and retry after commit. Record any accepted
differences explicitly. Production output sign-off and Python retirement
require named owners and an agreed rollback plan.
