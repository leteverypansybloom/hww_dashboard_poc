# Running the interim pipeline in GCP

This deployment is pending a live test. The unit tests use a fake BigQuery
client. The pipeline writes the interim reporting tables directly; py-common
continues to land and load raw data, and Dataform later replaces these rules.
The current Streamlit dashboard still reads local CSV files.

This page runs `wrangle.py` on workbooks mounted from the landing bucket.
To ingest them with py-common first (`ingest.py`, typed BigQuery tables)
and have `wrangle.py` read those instead, follow
[gcp_ingestion.md](gcp_ingestion.md).

## Resources and access

Use the approved region (for example `europe-west2`) for the job and dataset.
Create a separate interim dataset, never point this job at py-common raw tables
or a Dataform production dataset. The dataset must exist before a run.

Give the job service account Storage Object Viewer on the landing bucket,
BigQuery Data Editor on this dataset, and BigQuery Job User on the execution
project. Readers receive Data Viewer only where required by the DPIA. Use the
Cloud Run service identity; do not put a service-account key in an image.

Enable bucket versioning and agree retention with the data owner. This file
reader does not pin GCS generations. Finish uploads and prevent replacements
throughout a run, or copy the approved versions into an immutable batch prefix
and mount that batch. Record the selected batch in deployment records. The run
record's checksums identify content but cannot make concurrent uploads safe.

## Config and image

Copy `config.toml` to an ignored `config.local.toml`, keeping the column and
mapping settings. Change the following sections:

```toml
[paths]
input_folder = "/mnt/landing"
output_folder = "/tmp/hww-unused"
mappings_folder = "/app/mappings"
log_folder = "/tmp/logs"

[output]
target = "bigquery"
project = "${HWW_BQ_PROJECT}"
dataset = "${HWW_BQ_DATASET}"
location = "europe-west2"
```

Set each source's `file` to its exact relative landing path, for example
`was/agreed-was-name.xlsx`. For the survey remove `file_pattern` and set `file`
to its agreed fixed name. Match the py-common contract; changing a source file
name is a coordinated change. Keep `keep_other_free_text = false`.

The image must install this package with the `bigquery` extra and
`-c constraints.txt`, include the reviewed config and mappings at `/app`, and
run `python -m hww_dashboard.wrangle /app/config.local.toml`. Install from the
reviewed source; do not include workbooks, outputs, logs, credentials or git
history in its build context. Set `HWW_GIT_COMMIT` to the source commit and
`HWW_LOG_FORMAT=json`. Pin the Python base image and deploy an image digest.
The image has not yet been built or tested. The deployment team must build
and smoke-test it before enabling a schedule.

## Job configuration

Use one task with parallelism one and automatic retries disabled initially.
Do not start another execution while one is running: those settings limit
parallelism inside an execution, not across executions. Serialize scheduled and
manual starts through one orchestrator. Set memory and timeout after measuring
a representative run; each BigQuery operation currently waits up to 600 seconds.

Mount the landing bucket read-only at `/mnt/landing`. For an existing job:

```sh
gcloud run jobs update JOB --region=europe-west2 \
  --add-volume mount-path=/mnt/landing,type=cloud-storage,bucket=LANDING_BUCKET,readonly=true \
  --set-env-vars HWW_LOG_FORMAT=json,HWW_BQ_PROJECT=PROJECT,HWW_BQ_DATASET=DATASET,HWW_GIT_COMMIT=COMMIT
```

Replace every capitalized placeholder. Cloud Run mounts buckets as files,
including read-only mounts; see [Google's volume-mount instructions](https://docs.cloud.google.com/run/docs/configuring/jobs/cloud-storage-volume-mounts).
Start manually with `gcloud run jobs execute JOB --region=europe-west2 --wait`.

## Acceptance checks

1. Run on synthetic inputs into a disposable dataset. Verify table schemas,
   row counts and the report; check a `runs` record names the right commit and
   input checksums. Compare rows with the golden and hand-worked scenarios.
2. Test a missing source and an invalid mapping: the final rows stay unchanged.
3. Test denied dataset access and a failed staging load. Check error messages
   omit cell values and the job fails. Verify staging cleanup or expiry.
4. For the optional live pytest, set `HWW_BQ_TEST_PROJECT` and
   `HWW_BQ_TEST_DATASET`, then run
   `python -m pytest -W error -m integration tests/test_bigquery_output.py`.
   This overwrites tables with standard output names and appends a run record;
   use an empty disposable dataset, never a reporting dataset.
5. Test logs, warning alerts and missing-run monitoring before scheduling.

Final tables are created outside the publication transaction on the first run.
Their rows, the report and the appended run record are published in one
transaction. BigQuery supports these DML transactions; see
[Google's transaction guidance](https://docs.cloud.google.com/bigquery/docs/transactions).
On a schema mismatch the run stops. Review the schema change, back up the
approved dataset, and replace affected tables deliberately during a maintenance
window; this writer does not perform schema migrations.

## Schedule, monitoring and recovery

Start daily after the expected uploads are complete. This job reads the mounted
Excel files directly, so a later py-common completion time alone is insufficient
unless it also certifies those files are stable. The eventual coordinated
workflow should run ingestion, this interim transform (later Dataform), then
consumer checks in order.

Alert on failed executions and WARNING logs whose message starts
`Report needs attention:`. Also monitor the latest successful `runs.finished_at`
and the agreed arrival time of each source: an old file can be processed
successfully every day. Include an operator and backup in each alert. Test each
alert using synthetic data. Set budgets and review query/storage costs.

For uncertain query outcomes inspect the logged job id and `runs` before
retrying. For bad successful outputs restore approved inputs and rerun the
reviewed code and settings. Follow [the runbook](runbook.md), including the
retention decisions in [data protection](data_protection.md). BigQuery retains
replaced data through time travel and fail-safe, including staging data.
