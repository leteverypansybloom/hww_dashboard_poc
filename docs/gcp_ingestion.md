# Ingesting on GCP with py-common (typed route)

This guide takes the HWW workbooks from a GCS bucket to the dashboard,
using `ingest.py` and py-common's typed route:

```
workbooks uploaded to the landing bucket
  -> python ingest.py     checks each workbook against its contract and
                          loads it into a typed BigQuery table
  -> python wrangle.py    reads the newest load of each table and builds
                          the dashboard tables
  -> streamlit run dashboard.py
```

It is written to be followed in order, from an empty GCP project. Steps
1 to 7 run everything from your laptop, which is the quickest way to
prove it works. Step 8 runs it in GCP every day as a Cloud Run job.
Step 9 adds a trigger, so a workbook loads within a minute or so of
being uploaded, with the daily job kept as a catch-up for anything
missed.

> **Status.** This route has been tested end to end on local folders,
> and the GCP parts are unit-tested against a fake BigQuery client. It
> has not yet been run against a real GCP project, so treat the first
> run as a test and use a development project.

For how the same route runs on local folders, see the README section
"Ingesting with py-common first". The workbook contracts are in
`src/hww_dashboard/landing.py`.

## What you need

- A GCP project you can create buckets and BigQuery datasets in (or
  someone who can create them for you).
- The Google Cloud CLI (`gcloud` and `bq`) installed.
- This project installed on your laptop, with py-common (README, "Set
  up"). py-common is installed from GitHub, so you also need Git and
  access to the py-common repository, and `<GITHUB_ORG>` in
  `pyproject.toml` must be set to the organisation that hosts it.

Steps 6 and 7 use `python ingest.py` and `python wrangle.py`. Once the
project is installed, `hww-ingest` and `hww-wrangle` do the same from
any folder, and `hww-run` runs both in turn, as the daily job does.

## What gets created

| Resource | Used for |
|---|---|
| Landing bucket | Where the workbooks are uploaded, one folder per source |
| Store bucket | py-common's own copies: raw files, Parquet, quarantined files, audit records, the run lock |
| Dataset for the typed tables | `hww_signups`, `hww_survey`, `hww_was`, `hww_peer` and py-common's `audit` table |

Keep the landing and store buckets separate: py-common writes to the
store on every run, and in the landing bucket it would find its own
copies as new files.

## 1. Choose names

Run these in a terminal (bash shown; in PowerShell use
`$PROJECT = "..."`) and replace everything in angle brackets:

```bash
PROJECT="<PROJECT_ID>"
REGION="europe-west2"
LANDING_BUCKET="<LANDING_BUCKET>"   # e.g. hww-landing-dev
STORE_BUCKET="<STORE_BUCKET>"       # e.g. hww-store-dev
DATASET="<DATASET>"                 # e.g. hww_landed_dev
```

## 2. Sign in

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project "$PROJECT"
```

The second command creates the credentials that `ingest.py` and
`wrangle.py` use. py-common's `docs/LOCAL_GCP_AUTHENTICATION.md` has
more detail and troubleshooting.

## 3. Create the buckets and dataset

```bash
gcloud storage buckets create "gs://$LANDING_BUCKET" \
  --location="$REGION" --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update "gs://$LANDING_BUCKET" --versioning

gcloud storage buckets create "gs://$STORE_BUCKET" \
  --location="$REGION" --uniform-bucket-level-access --public-access-prevention

bq --location="$REGION" mk --dataset "$PROJECT:$DATASET"
```

Versioning on the landing bucket keeps every upload of a file, so you
can upload the same file name each month and still get any earlier
version back.

Then create py-common's audit table. It must exist before the first
load; the typed tables themselves are created on their first load.

```bash
bq query --use_legacy_sql=false "
CREATE TABLE IF NOT EXISTS \`$PROJECT.$DATASET.audit\` (
  filename STRING,
  checksum STRING,
  destination STRING,
  source_version STRING,
  row_count INT64,
  outcome STRING,
  timestamp TIMESTAMP
)"
```

## 4. Give yourself access

Whoever runs `ingest.py` (you now, a service account in step 8) needs:

| Role | On | Why |
|---|---|---|
| Storage Object Viewer | Landing bucket | List and download the workbooks |
| Storage Object Creator and Storage Object Viewer | Store bucket | Write and read py-common's copies and audit records |
| Storage Object User, limited to `locks/` | Store bucket | Release the run lock |
| BigQuery Data Editor | The dataset | Create the typed tables, load them, write the audit table |
| BigQuery Job User | The project | Run load jobs and queries |

Project owners already have all of these. Otherwise ask for them, or
run the commands in py-common's `docs/GCP_SETUP.md`, section 3, with
your own account as the member. Reading the tables back (`wrangle.py`,
step 7) needs only BigQuery Data Viewer on the dataset and Job User.

## 5. Upload the workbooks

Each source has its own folder in the landing bucket, under a common
prefix (`hww` here). The folder names must be exactly `signups`,
`survey`, `was` and `peer`:

```bash
gcloud storage cp "../dummy_HWW monitoring and reporting.xlsx" "gs://$LANDING_BUCKET/hww/signups/"
gcloud storage cp ../dummy-healthy-working-wales-employer-survey-tool-2026-09-23.xlsx "gs://$LANDING_BUCKET/hww/survey/"
gcloud storage cp ../dummy_was_database.xlsx "gs://$LANDING_BUCKET/hww/was/"
gcloud storage cp ../dummy_peer_montoring.xlsx "gs://$LANDING_BUCKET/hww/peer/"
```

(Run from `hww_poc_code`; the dummy workbooks are in the folder above.)

Things to know about uploads:

- **File names matter.** Sign-ups, WAS and peer mentoring must keep the
  exact names given by `file` in `config.toml`. A file under any other
  name is quarantined. To change a name, change `file` in the config
  first.
- **Each upload is the complete list.** Upload the whole workbook each
  time, not just new rows. The pipeline reads only the newest load of
  each source.
- **Only the folder itself is read,** not sub-folders.
- **The survey** can have any name that matches `file_pattern`. Only
  the newest export in the folder is loaded: the one with the latest
  date in its name, then the most recently uploaded. Older exports can
  stay in the folder; they're ignored.

## 6. Configure and run the ingestion

Make a local copy of the config for GCP. Files ending `.local.toml` are
ignored by git.

```bash
cp config.toml gcp.local.toml
```

In `gcp.local.toml`, set the `[landed]` section to:

```toml
[landed]
read = true
target = "gcp"
project = "${HWW_GCP_PROJECT}"
landing_bucket = "${HWW_LANDING_BUCKET}"
landing_prefix = "hww"
store_bucket = "${HWW_STORE_BUCKET}"
dataset = "${HWW_LANDED_DATASET}"
```

The `${...}` values are read from environment variables, so the file
holds no project-specific names. Set them and run the ingestion:

```bash
export HWW_GCP_PROJECT="$PROJECT"
export HWW_LANDING_BUCKET="$LANDING_BUCKET"
export HWW_STORE_BUCKET="$STORE_BUCKET"
export HWW_LANDED_DATASET="$DATASET"

python ingest.py gcp.local.toml
```

(In PowerShell: `$env:HWW_GCP_PROJECT = "..."` and so on.)

It prints one line per file:

```
signups: dummy_HWW monitoring and reporting.xlsx: loaded, 200 row(s)
survey: dummy-healthy-working-wales-employer-survey-tool-2026-09-23.xlsx: loaded, 1 row(s)
was: dummy_was_database.xlsx: loaded, 35 row(s)
peer: dummy_peer_montoring.xlsx: loaded, 11 row(s)
```

The exit code is 0 when every file loaded or was already loaded. It is
1 when a file was quarantined or failed, or a source's folder is empty;
the line for that file says why.

Check the result in BigQuery:

```bash
bq query --use_legacy_sql=false "
SELECT destination, filename, row_count, outcome, timestamp
FROM \`$PROJECT.$DATASET.audit\`
ORDER BY timestamp DESC"
```

Each typed table has the columns its contract lists, named for
BigQuery (`Date of Enquiry` becomes `date_of_enquiry`), plus
`excel_row` (the row in the workbook) and `_loaded_at` (when it was
loaded). Personal and unused columns are not there.

Run `python ingest.py gcp.local.toml` again: every file should now say
`skipped`, and no rows are added.

## 7. Build the tables and open the dashboard

```bash
python wrangle.py gcp.local.toml
streamlit run dashboard.py
```

With `read = true`, `wrangle.py` reads the newest load of each typed
table instead of the workbooks. The tables, `data_quality_report.md`
and `run_record.json` are written to `output/` as usual; the run
record names the table and load time each input came from. The
dashboard reads `output/`.

`[output] target = "bigquery"` instead writes the tables to a BigQuery
dataset (see `docs/gcp.md`). The Streamlit dashboard can't read those
yet, so keep `folder` while you're using it.

## 8. Run it every day in GCP

Once steps 1 to 7 work from your laptop, the same thing can run on its
own each day as a Cloud Run job. The job runs `hww-run`: py-common
ingestion first, then, only if every file loaded or was already loaded,
the pipeline. If ingestion fails (a quarantined file, an empty folder),
the reporting tables are left as they were and the job shows as failed.

In GCP the pipeline writes its tables to a BigQuery dataset (the
"reporting dataset" below), not to CSV files. The Streamlit dashboard
can't read those yet; Power BI or Dataform would.

The image is built in GCP with Cloud Build, so you don't need Docker on
your laptop. It is built in two parts: py-common's own image first,
then this project's image on top of it. That way the build never needs
access to py-common's GitHub repository.

### 8a. Names and APIs

Add these to the names from step 1:

```bash
REPORT_DATASET="<REPORT_DATASET>"   # e.g. hww_report_dev
REPO="<ARTIFACT_REPO>"               # e.g. hww
SA_NAME="<SERVICE_ACCOUNT_NAME>"     # e.g. hww-job
SA="$SA_NAME@$PROJECT.iam.gserviceaccount.com"
JOB="<JOB_NAME>"                     # e.g. hww-daily
REGISTRY="$REGION-docker.pkg.dev/$PROJECT/$REPO"
PY_COMMON_COMMIT="<PY_COMMON_COMMIT>" # the commit pinned in pyproject.toml
```

Turn on the services the job uses (once per project):

```bash
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com cloudscheduler.googleapis.com \
  bigquery.googleapis.com storage.googleapis.com
```

### 8b. Reporting dataset

```bash
bq --location="$REGION" mk --dataset "$PROJECT:$REPORT_DATASET"
```

The pipeline creates its tables there on the first run.

### 8c. Service account

```bash
gcloud iam service-accounts create "$SA_NAME" \
  --display-name="HWW daily job"
```

Give it the roles from step 4, with the service account as the member
(`--member="serviceAccount:$SA"`; py-common's `docs/GCP_SETUP.md`,
section 3, has the commands). It also needs to write the reporting
dataset:

```bash
bq add-iam-policy-binding --member="serviceAccount:$SA" \
  --role="roles/bigquery.dataEditor" "$PROJECT:$REPORT_DATASET"
```

### 8d. Somewhere to keep the images

```bash
gcloud artifacts repositories create "$REPO" \
  --repository-format=docker --location="$REGION"
```

### 8e. Build py-common's image

`gcloud builds submit` uploads your source to a bucket first. By default
that is `<PROJECT>_cloudbuild`, which many organisations don't let users
create or use, giving *"The user is forbidden from accessing the bucket
[<PROJECT>_cloudbuild]"*. So name a bucket you can write to, for
example the store bucket, and send the build logs to Cloud Logging
rather than a bucket (both build configs here do that):

```bash
STAGING="gs://$STORE_BUCKET/cloudbuild-source"
```

From a copy of the py-common repository at the commit pinned in this
project's `pyproject.toml` (the `landing` extra):

```bash
cd <path to py-common>
git checkout "$PY_COMMON_COMMIT"
BASE_IMAGE="$REGISTRY/py-common:$PY_COMMON_COMMIT"
gcloud builds submit \
  --config=<path to hww_poc_code>/cloudbuild.py-common.yaml \
  --substitutions="_IMAGE=$BASE_IMAGE" \
  --gcs-source-staging-dir="$STAGING" .
```

This uploads the folder (leaving out what `.gitignore` lists) and
builds py-common's `Dockerfile` in GCP. It takes a few minutes.
Rebuild it only when you move to a new py-common commit.

If it is still refused, ask for the Service Usage Consumer role
(`roles/serviceusage.serviceUsageConsumer`) on the project, and
Storage Object Admin on the staging bucket.

### 8f. Build this project's image

From this project's folder:

```bash
cd <path to hww_poc_code>
IMAGE="$REGISTRY/hww-job:$(git rev-parse --short HEAD)"
gcloud builds submit --config=cloudbuild.yaml \
  --substitutions="_BASE_IMAGE=$BASE_IMAGE,_IMAGE=$IMAGE" \
  --gcs-source-staging-dir="$STAGING" .
```

One image does both jobs: the daily job (step 8g) and the
upload-triggered service (step 9).

This builds the `Dockerfile` here on top of py-common's image: it
installs this package, and copies in `config.gcp.toml` and `mappings/`.
No workbooks, outputs, logs or local settings go into the image
(`.dockerignore`). The build ends by checking that the code, py-common
and the config load. Tag each image with the commit it was built from,
as above, so you always know what is running.

If the build can't pull py-common's image, give the Cloud Build service
account (`<PROJECT_NUMBER>@cloudbuild.gserviceaccount.com`) the
Artifact Registry Reader role on the repository.

### 8g. Create the job

```bash
gcloud run jobs deploy "$JOB" \
  --image="$IMAGE" --region="$REGION" \
  --service-account="$SA" --tasks=1 --max-retries=0 \
  --set-env-vars="HWW_GCP_PROJECT=$PROJECT,HWW_LANDING_BUCKET=$LANDING_BUCKET,HWW_STORE_BUCKET=$STORE_BUCKET,HWW_LANDED_DATASET=$DATASET,HWW_BQ_PROJECT=$PROJECT,HWW_BQ_DATASET=$REPORT_DATASET"
```

The image runs `hww-run /app/config.gcp.toml`. That config is
`config.toml` with only the locations changed: the landing bucket
(`hww/<source>/` folders, as in step 5), the typed tables and the
reporting dataset all come from the environment variables above. Every
variable must be set, or the job stops saying which is missing.

`--max-retries=0`: a rerun is safe (loaded files are skipped), but it
should be deliberate.

### 8h. Run it once by hand

```bash
gcloud run jobs execute "$JOB" --region="$REGION" --wait
```

Then check:

- the execution finished without errors (in the console, Cloud Run →
  Jobs → the job → Executions; the logs are there too);
- the `audit` table in `$DATASET` has today's loads (or, if the files
  were already loaded in step 6, nothing new: the logs say `skipped`);
- the reporting dataset has the tables (`dim_employer`,
  `fact_engagement`, ...) and a `runs` row for this run.

### 8i. Schedule it

```bash
gcloud iam service-accounts create "$JOB-scheduler"

gcloud run jobs add-iam-policy-binding "$JOB" --region="$REGION" \
  --member="serviceAccount:$JOB-scheduler@$PROJECT.iam.gserviceaccount.com" \
  --role="roles/run.invoker"

gcloud scheduler jobs create http "$JOB-daily" --location="$REGION" \
  --schedule="0 6 * * *" --time-zone="Europe/London" \
  --http-method=POST \
  --uri="https://run.googleapis.com/v2/projects/$PROJECT/locations/$REGION/jobs/$JOB:run" \
  --oauth-service-account-email="$JOB-scheduler@$PROJECT.iam.gserviceaccount.com"
```

That runs it at 6am every day. Daily rather than monthly, so a late or
corrected upload is picked up the next morning; a run with nothing new
costs almost nothing.

### 8j. Alerts

At minimum, alert on failed executions, so a quarantined file or a
missing folder doesn't go unnoticed. The image sets
`HWW_LOG_FORMAT=json`, so the logs are structured, and log-based
alerts can match on `jsonPayload.message` and `severity`, as in
py-common's `docs/GCP_SETUP.md`, section 7. Useful ones:

- `severity>=ERROR`: any failed or quarantined file, or a stopped run;
- `jsonPayload.message:"quarantined"`: a workbook rejected by its
  contract;
- `jsonPayload.message:"Report needs attention:"`: the pipeline's data
  quality report has something to look at.

### Updating the job

After a code, config or mapping change: commit it, rebuild this
project's image (8f) and deploy the new tag (8g, `gcloud run jobs
deploy` again). After a py-common change: update the commit in
`pyproject.toml`, rebuild both images (8e, then 8f) and deploy.

## 9. Run on upload, with the daily job as a catch-up

Step 8 runs once a day. To load a workbook within a minute or so of it
landing, add an upload trigger, following the team's pattern:

```
workbook uploaded to the landing bucket (data project)
  -> bucket notification to a Pub/Sub topic (app project)
  -> Eventarc trigger
  -> Cloud Run service (app project), same image as the daily job:
       ingests the folder the file landed in, then, if nothing was
       quarantined, rebuilds the reporting tables
```

**Keep the daily job (step 8i).** Pub/Sub can drop an event, for
example if the service is down for more than a day, and the daily run
loads anything that was missed. The two don't get in each other's way:

- **One load at a time.** Both take py-common's lock in the store
  bucket. If the service and the job meet, one is refused; the job
  tries again tomorrow, and Pub/Sub delivers the event again.
- **Nothing loads twice.** A file already loaded is skipped, by the
  store's marker and by the audit table's check inside the load. A
  repeated event, or the daily job after an event, finds it loaded.
- **Rebuilding is repeatable.** The tables are rebuilt from the newest
  load of every source, so rebuilding twice gives the same tables.
- **A quarantined file stops the rebuild,** in the service as in the
  job, so the reporting tables keep the last complete set.

The one thing to know: when the four workbooks arrive at different
times, each upload rebuilds the tables, so for a while they mix this
month's file for one source with last month's for another. The daily
job behaves the same way. If that matters, upload all four together.

### 9a. Names

Your team's guide splits two projects. Add:

```bash
APP_PROJECT="<APP_PROJECT_ID>"   # Pub/Sub, Cloud Run and Eventarc
DATA_PROJECT="<DATA_PROJECT_ID>" # the buckets and BigQuery datasets
TOPIC="<PUBSUB_TOPIC_NAME>"      # e.g. hww-landing-uploads
SERVICE="<CLOUD_RUN_SERVICE_NAME>" # e.g. hww-on-upload
```

If everything is in one project, set both to `$PROJECT`. The
`HWW_GCP_PROJECT`, `HWW_BQ_PROJECT` and bucket and dataset variables
(step 8g) always name the data project, where the buckets and tables
are; the service itself runs in the app project.

### 9b. Permissions

Whoever runs these commands needs, as the team's guide lists:
`pubsub.topics.create`, `pubsub.topics.get`, `pubsub.topics.publish`
and `pubsub.topics.getIamPolicy` on the app project, and
`storage.buckets.update` on the landing bucket. Ask the Data
Engineering team.

The service runs as the service account from step 8c. It needs the
roles from step 4 and step 8c in the **data** project (buckets and
datasets), and, in the app project, Eventarc Event Receiver and Cloud
Run Invoker on the service (below).

### 9c. Topic and bucket notification

```bash
gcloud pubsub topics create "$TOPIC" --project="$APP_PROJECT"

gcloud storage buckets notifications create "gs://$LANDING_BUCKET" \
  --project="$DATA_PROJECT" \
  --topic="projects/$APP_PROJECT/topics/$TOPIC" \
  --payload-format=json --event-types=OBJECT_FINALIZE
```

`OBJECT_FINALIZE` means only new uploads publish a message, not deletes
or changes to a file's details. The command also lets the data
project's Cloud Storage publish to the topic.

### 9d. Deploy the service

The same image as the daily job (step 8f), started as a service by the
functions-framework instead of `hww-run`:

```bash
gcloud run deploy "$SERVICE" \
  --project="$APP_PROJECT" --region="$REGION" --image="$IMAGE" \
  --service-account="$SA" --no-allow-unauthenticated \
  --max-instances=1 --concurrency=1 --timeout=540 \
  --command="functions-framework" \
  --args="--source=/app/src/hww_dashboard/service.py,--target=on_upload,--signature-type=cloudevent" \
  --set-env-vars="HWW_GCP_PROJECT=$DATA_PROJECT,HWW_LANDING_BUCKET=$LANDING_BUCKET,HWW_STORE_BUCKET=$STORE_BUCKET,HWW_LANDED_DATASET=$DATASET,HWW_BQ_PROJECT=$DATA_PROJECT,HWW_BQ_DATASET=$REPORT_DATASET"

gcloud run services add-iam-policy-binding "$SERVICE" \
  --project="$APP_PROJECT" --region="$REGION" \
  --member="serviceAccount:$SA" --role="roles/run.invoker"

gcloud projects add-iam-policy-binding "$APP_PROJECT" \
  --member="serviceAccount:$SA" --role="roles/eventarc.eventReceiver"
```

| Setting | Why |
|---|---|
| `--max-instances=1 --concurrency=1` | One upload is handled at a time. When four files land together, the later events wait their turn rather than being refused by the lock. |
| `--timeout=540` | Below the Pub/Sub acknowledgement deadline set in 9e, so a long run isn't delivered again while it is still going. |
| `--no-allow-unauthenticated` | Only Eventarc, as the service account, can call it. |

### 9e. The Eventarc trigger

```bash
gcloud eventarc triggers create "$TOPIC-trigger" \
  --project="$APP_PROJECT" --location="$REGION" \
  --destination-run-service="$SERVICE" \
  --destination-run-region="$REGION" \
  --event-filters="type=google.cloud.pubsub.topic.v1.messagePublished" \
  --transport-topic="projects/$APP_PROJECT/topics/$TOPIC" \
  --service-account="$SA"

SUBSCRIPTION=$(gcloud eventarc triggers describe "$TOPIC-trigger" \
  --project="$APP_PROJECT" --location="$REGION" \
  --format="value(transport.pubsub.subscription)")
gcloud pubsub subscriptions update "$SUBSCRIPTION" \
  --project="$APP_PROJECT" --ack-deadline=600
```

The deadline starts at 10 seconds; 600 gives a run time to finish
before Pub/Sub tries again.

### 9f. Check it works

1. Upload a workbook again, e.g.
   `gcloud storage cp ../dummy_was_database.xlsx "gs://$LANDING_BUCKET/hww/was/"`.
2. In the console, Cloud Run → Services → the service → Logs. Within a
   minute or so you should see `Upload gs://...: running ...`, then
   `Upload handled: rebuilt`.
3. Upload a file to a folder with no pipeline, e.g. `hww/test/`: the
   logs say `Ignoring upload` and `Upload handled: ignored`.

What the service does with each event:

| Event | Result |
|---|---|
| New file in a source's folder | That folder is ingested, then the tables are rebuilt |
| The same event delivered again | Files are already loaded (skipped), and the tables are rebuilt again: same result |
| A file is quarantined | Tables not rebuilt; logged at ERROR; not retried, as retrying won't fix the file |
| The rebuild stops on something a person must fix (a mapping, a setting) | Logged at ERROR; not retried |
| A file fails, the lock is held, or BigQuery fails | The event is retried by Pub/Sub |
| Upload to another folder or bucket, or a delete | Ignored |

The alerts in step 8j cover the service too: in their filters, add
`resource.type="cloud_run_revision"` alongside the job's
`cloud_run_job`.

If triggers fail with permission errors on older projects, the app
project's Pub/Sub service agent
(`service-<APP_PROJECT_NUMBER>@gcp-sa-pubsub.iam.gserviceaccount.com`)
also needs the Service Account Token Creator role.

## When something goes wrong

| What you see | What to do |
|---|---|
| `quarantined` with a column name | The workbook doesn't match its contract: a new or missing column, or a value of the wrong type. Fix the workbook and upload it again, or, if the change is intended, update the contract in `src/hww_dashboard/landing.py` and the matching `config.toml` setting. The file is kept in `gs://$STORE_BUCKET/quarantine/`. |
| `quarantined ... wrong file name, expected ...` | The file was uploaded under the wrong name. Delete it from the landing folder and upload it under the name in `config.toml`. |
| `no files in its landing folder` | Nothing in `hww/<source>/`. Check the prefix and folder names. |
| `403` or `Permission denied` | A role from step 4 is missing. |
| `gcloud builds submit`: forbidden from accessing the bucket `<PROJECT>_cloudbuild` | Add `--gcs-source-staging-dir=gs://<bucket you can write>/cloudbuild-source` and use the build configs in this repo, which keep logs out of buckets (step 8e). |
| `Not found: Table ... audit` | The audit table wasn't created (step 3). |
| A run is refused because of a lock | A previous run was stopped. Wait an hour for the lock to expire, or check nothing is running and delete the lock object named in the error. |
| `wrangle.py` says "No landed table" or "no rows" | Run `ingest.py` first, and check `[landed]` points at the same dataset. |

py-common's `docs/RUNBOOK.md` covers reloading, undoing a bad load and
renaming a workbook.
