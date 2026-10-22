# Ingesting on GCP with py-common (typed route)

This guide takes the HWW workbooks from a GCS bucket into BigQuery and
on to the reporting tables, using py-common's typed route:

```
workbook uploaded to the landing bucket
  -> ingestion (py-common): checks each workbook against its contract
     and loads it into a typed BigQuery table
  -> pipeline: reads the newest load of each table and builds the
     reporting tables
```

In GCP this runs once a day as a Cloud Run job, and, optionally, within
a minute of an upload as a Cloud Run service.

> **Status.** Tested end to end on local folders. The daily job has been
> built and run in a development project. The two-project layout below
> and the upload trigger haven't been run yet, so treat the first run of
> each as a test.

The workbook contracts are in `src/hww_dashboard/landing.py`. For the
same route on local folders, see the README section "Ingesting with
py-common first".

## How it's laid out

Following the team's pattern, things that **run** are in the app
project and things that **hold data** are in the data project:

| App project | Data project |
|---|---|
| Artifact Registry repository (the container images) | Landing bucket (workbooks are uploaded here) |
| Cloud Run job (daily) and service (on upload) | Store bucket (py-common's copies, audit records, run lock) |
| Cloud Scheduler (starts the job each morning) | `hww_landed` dataset (typed tables and `audit`) |
| Pub/Sub topic and Eventarc trigger (upload events) | `hww_reporting` dataset (reporting tables) |
| The service account the job, service and scheduler run as | |

The pipeline's service account lives in the app project and is given
access to the data project's buckets and datasets. The code doesn't care
which project anything is in: every location is set when the job is
deployed.

Recommended names (change them to fit your conventions; the code doesn't
depend on any of them):

| What | Name |
|---|---|
| Landing bucket | `<prefix>-hww-landing-dev` |
| Store bucket | `<prefix>-hww-store-dev` |
| Datasets | `hww_landed`, `hww_reporting` |
| Artifact Registry repository | `hww` |
| Service account | an existing one for this work, or `hww-pipeline` |
| Cloud Run job / service | `hww-daily` / `hww-on-upload` |
| Scheduler job | `hww-daily-0600` |
| Pub/Sub topic / Eventarc trigger | `hww-landing-uploads` / `hww-landing-uploads-trigger` |

Bucket names are global across all of Google Cloud, so they need an
organisation prefix. Dataset names can't contain hyphens. If your
projects aren't per environment, add `_dev` to the datasets too.
Existing buckets and datasets work just as well: the guide only needs
their names.

## Who does what

Creating buckets and datasets and granting roles usually needs an admin
(for example the Data Engineering manager). Once they've set up the
section below, everything else is yours.

| Step | Who |
|---|---|
| Set-up below: buckets, datasets, repository, roles | Admin |
| 1b: Create the `audit` table | You |
| 1–4: Try the ingestion from your laptop (optional) | You |
| 5–9: Build the images, deploy the daily job, run it, schedule it, alert | You |
| 10a: Deploy the upload service | You |
| 10b: Topic, bucket notification and Eventarc trigger | Admin |
| 11: Move from a test set-up | You, then the admin removes the old access |

## What the admin sets up

**Data project**

- Landing bucket: uniform bucket-level access, public access
  prevention, **object versioning on** (keeps every upload).
- Store bucket: uniform bucket-level access, public access prevention.
  Separate from the landing bucket, or the pipeline would find its own
  copies as new uploads.
- Datasets `hww_landed` and `hww_reporting`, in `europe-west2`. The
  pipeline creates its tables, apart from `audit`, which you create
  yourself once you have BigQuery Data Editor (step 1b).

**App project**

- Artifact Registry repository `hww` (Docker, `europe-west2`).
- APIs on: Cloud Run, Artifact Registry, Cloud Scheduler, Pub/Sub,
  Eventarc (and BigQuery and Cloud Storage in the data project).
- The service account: an existing one for this work is fine. The job,
  the upload service and the scheduler all run as it.

**Roles for the service account**

| Role | On |
|---|---|
| Storage Object Viewer | Landing bucket |
| Storage Object Creator and Storage Object Viewer | Store bucket |
| Storage Object User, condition: objects under `locks/` only | Store bucket |
| BigQuery Data Editor | `hww_landed` and `hww_reporting` |
| BigQuery Job User | Data project |
| Cloud Run Invoker | The daily job and the upload service (or the app project) |
| Eventarc Event Receiver | App project |

**Roles for you (development)**

| Role | On |
|---|---|
| Artifact Registry Writer | `hww` repository |
| Cloud Run Developer, Logs Viewer | App project |
| Cloud Scheduler Admin, Monitoring Editor (or the admin does steps 8–9) | App project |
| Service Account User | The service account |
| Storage Object User | Landing bucket (to upload test files) |
| Storage Object Viewer | Store bucket |
| BigQuery Data Viewer | Both datasets |
| BigQuery Job User | Data project |

For steps 3–4 from your laptop, also Storage Object Creator on the store
bucket and BigQuery Data Editor on both datasets. People who upload the
workbooks each month need only Storage Object User on the landing
bucket.

**Upload trigger (step 10b), once the service is deployed**

```bash
gcloud pubsub topics create hww-landing-uploads --project=<APP_PROJECT_ID>

gcloud storage buckets notifications create gs://<LANDING_BUCKET> \
  --project=<DATA_PROJECT_ID> \
  --topic=projects/<APP_PROJECT_ID>/topics/hww-landing-uploads \
  --payload-format=json --event-types=OBJECT_FINALIZE

gcloud eventarc triggers create hww-landing-uploads-trigger \
  --project=<APP_PROJECT_ID> --location=europe-west2 \
  --destination-run-service=hww-on-upload \
  --destination-run-region=europe-west2 \
  --event-filters="type=google.cloud.pubsub.topic.v1.messagePublished" \
  --transport-topic=projects/<APP_PROJECT_ID>/topics/hww-landing-uploads \
  --service-account=<SERVICE_ACCOUNT_EMAIL>

SUBSCRIPTION=$(gcloud eventarc triggers describe hww-landing-uploads-trigger \
  --project=<APP_PROJECT_ID> --location=europe-west2 \
  --format="value(transport.pubsub.subscription)")
gcloud pubsub subscriptions update "$SUBSCRIPTION" \
  --project=<APP_PROJECT_ID> --ack-deadline=600
```

The 600-second acknowledgement deadline stops a run that takes a few
minutes being resent while it's still going. On older projects, the app
project's Pub/Sub service agent may also need Service Account Token
Creator.

## What you need

- The set-up above, done.
- **Cloud Shell** (the **>_** icon at the top of the GCP console). Steps
  5 onwards are bash commands written for it. It has `gcloud`, `bq` and
  Docker, and is already signed in as you.
- For steps 3–4 only: this project installed on your laptop with
  py-common (README, "Set up").

## Where to run what

Each step says where it runs. Your laptop needs no Docker and no extra
GCP rights beyond the optional steps 3–4.

| Where | Steps | Why there |
|---|---|---|
| **Laptop, PowerShell** | 3–4 (optional test), 5a (zip the code) | The code and your Python set-up are on the laptop |
| **Either** | 2 (upload workbooks), 5b (copy zips) | `gcloud storage cp` works the same in both, or use the console |
| **Cloud Shell, bash** | 1, 5b–5c, 6–11 | Docker is there, you're already signed in, and the commands are bash |

**Things that don't work in PowerShell,** and why those steps are in
Cloud Shell:

| In bash (Cloud Shell) | In PowerShell | Notes |
|---|---|---|
| `NAME="value"` | `$NAME = "value"` | A bash-style line does nothing useful in PowerShell, and the variable stays blank. Blank variables gave invalid image names and a job missing a setting. |
| `export NAME="value"` | `$env:NAME = "value"` | For settings a program reads (steps 3–4). |
| A line ending in `\` continues on the next | Backtick `` ` `` instead | Pasting bash's multi-line commands into PowerShell breaks them. Paste as one line, or use Cloud Shell. |
| `sed`, `unzip`, `rm -rf` | Not available | Use Cloud Shell for these. |
| `docker` | Usually not installed, or blocked, on work laptops | Build in Cloud Shell (step 5). |
| `hww-ingest`, `hww-run` | Often blocked ("Access denied") by work policy | Use `python -m hww_dashboard.landing`, `python -m hww_dashboard.job` and so on (README). |

If a bash command in Cloud Shell leaves the prompt at `>`, it's waiting
for a closing quote: press Ctrl+C and paste it again as one line.

## 1. Names (Cloud Shell)

Every Cloud Shell step uses these. They're forgotten when the session
ends, so run this block again whenever you come back:

```bash
APP_PROJECT="<APP_PROJECT_ID>"
DATA_PROJECT="<DATA_PROJECT_ID>"
REGION="europe-west2"
LANDING_BUCKET="<landing bucket>"
STORE_BUCKET="<store bucket>"
DATASET="hww_landed"
REPORT_DATASET="hww_reporting"
SA="<the service account's email>"
REGISTRY="$REGION-docker.pkg.dev/$APP_PROJECT/hww"
JOB="hww-daily"
SERVICE="hww-on-upload"
```

Check there are no blanks: `echo "$REGISTRY" "$SA"` should print two full
names. (In PowerShell, write each as `$NAME = "value"`.)

## 1b. Create the audit table (BigQuery console or Cloud Shell)

py-common records every load in an `audit` table and checks it before
loading, so the table must exist before the first run. The pipeline
creates all its other tables itself. Creating it needs BigQuery Data
Editor on `hww_landed`, which you have from the set-up. Do it once.

In the BigQuery console, open the data project, click **Compose new
query**, paste this and click **Run**:

```sql
CREATE TABLE IF NOT EXISTS `<DATA_PROJECT_ID>.hww_landed.audit` (
  filename STRING, checksum STRING, destination STRING,
  source_version STRING, row_count INT64, outcome STRING,
  timestamp TIMESTAMP
);
```

Or in Cloud Shell, with the names from step 1:

```bash
bq query --project_id="$DATA_PROJECT" --use_legacy_sql=false "CREATE TABLE IF NOT EXISTS \`$DATA_PROJECT.$DATASET.audit\` (filename STRING, checksum STRING, destination STRING, source_version STRING, row_count INT64, outcome STRING, timestamp TIMESTAMP)"
```

`IF NOT EXISTS` makes it safe to run again.

## 2. Upload the workbooks (console, or either shell)

Each source has its own folder in the landing bucket, under `hww/`. The
folder names must be exactly `signups`, `survey`, `was` and `peer`:

```
gs://<landing bucket>/hww/signups/<the monitoring and reporting workbook>
gs://<landing bucket>/hww/survey/<the survey export>
gs://<landing bucket>/hww/was/<the WAS database>
gs://<landing bucket>/hww/peer/<the peer mentoring workbook>
```

Upload in the console (Cloud Storage → the bucket → Create folder,
Upload files), or with `gcloud storage cp`: in Cloud Shell,
`gcloud storage cp <file> "gs://$LANDING_BUCKET/hww/was/"`; in
PowerShell, `gcloud storage cp "<file>" gs://<landing bucket>/hww/was/`.

- **File names matter.** Sign-ups, WAS and peer mentoring must keep the
  exact names given by `file` in `config.toml`; a file under any other
  name is quarantined. To change a name, change `file` in the config
  first (and rebuild the image, step 5).
- **Upload the whole workbook each time,** not just new rows. The
  pipeline reads only the newest load of each source.
- **Only the folder itself is read,** not sub-folders.
- **The survey** can have any name that matches `file_pattern`. Only the
  newest export in the folder is loaded (latest date in its name, then
  most recently uploaded); older ones are ignored.

## 3. Optional: try the ingestion from your laptop (PowerShell)

Quickest way to check the buckets, datasets and contracts before
deploying anything. Needs the extra laptop roles in "What the admin sets up".

```powershell
gcloud auth application-default login
copy config.toml gcp.local.toml
```

In `gcp.local.toml`, set `[landed]` to:

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

Then (PowerShell, with your names):

```powershell
$env:HWW_GCP_PROJECT = "<DATA_PROJECT_ID>"
$env:HWW_LANDING_BUCKET = "<landing bucket>"
$env:HWW_STORE_BUCKET = "<store bucket>"
$env:HWW_LANDED_DATASET = "hww_landed"
python -m hww_dashboard.landing gcp.local.toml
```

It prints one line per file:

```
signups: dummy_HWW monitoring and reporting.xlsx: loaded, 200 row(s)
survey: dummy-healthy-working-wales-employer-survey-tool-2026-09-23.xlsx: loaded, 1 row(s)
was: dummy_was_database.xlsx: loaded, 35 row(s)
peer: dummy_peer_montoring.xlsx: loaded, 11 row(s)
```

Run it again: every file now says `skipped`. Exit code 0 means every
file loaded or was already loaded; 1 means one was quarantined or failed,
or a folder was empty, and its line says why.

`project` here is the **data** project, where the buckets and datasets
are. (If work policy blocks commands like `hww-ingest`, `python -m` runs
the same thing; see the README.)

## 4. Optional: build the tables on your laptop (PowerShell)

```powershell
python -m hww_dashboard.wrangle gcp.local.toml
python -m streamlit run dashboard.py
```

With `read = true` the pipeline reads the typed tables instead of
workbooks, and writes the tables to `output/`, which the Streamlit
dashboard reads.

## 5. Build the images (laptop, then Cloud Shell)

One image runs both the daily job and the upload service. It's built in
two layers: py-common's own image first, then this project's on top, so
the build never needs access to py-common's GitHub repository. Building
in Cloud Shell with Docker needs only Artifact Registry Writer on the
`hww` repository (no Cloud Build, staging bucket or logging
permissions).

**5a. Zip the code (laptop, PowerShell).** `git archive` includes only what's
committed, so `.venv`, data folders and local configs stay out:

```powershell
# in your py-common folder: the commit hww_dashboard_poc's pyproject.toml pins
git archive --format=zip -o $HOME\py-common.zip <py-common commit>

# in your hww_dashboard_poc folder
git archive --format=zip -o $HOME\hww_dashboard_poc.zip HEAD -- Dockerfile .dockerignore pyproject.toml constraints.txt README.md LICENSE config.gcp.toml src mappings
git rev-parse --short HEAD
```

The last command prints this project's commit; it becomes the image's
tag. The second zip holds only what the image needs; the full
repository's test workbooks can be blocked by upload filters.

**5b. Get the zips into Cloud Shell (either).** Either **⋮ → Upload** in Cloud
Shell, or, if the browser upload is blocked, copy them through a bucket
you can write to, first from the laptop (PowerShell):

```powershell
gcloud storage cp $HOME\hww_dashboard_poc.zip gs://<a bucket you can write>/tmp/
```

then into Cloud Shell (bash):

```bash
gcloud storage cp gs://<a bucket you can write>/tmp/hww_dashboard_poc.zip ~
```

If Cloud Shell says there's no active account, run `gcloud auth login`
(or `gcloud config set account <your email>`) first.

Then unzip:

```bash
cd ~
rm -rf py-common hww_dashboard_poc
unzip -q py-common.zip -d py-common
unzip -q hww_dashboard_poc.zip -d hww_dashboard_poc
```

**5c. Build and push (Cloud Shell).**

```bash
gcloud config set project "$APP_PROJECT"
gcloud auth configure-docker "$REGION-docker.pkg.dev"

PY_COMMON_COMMIT="<py-common commit>"
BASE_IMAGE="$REGISTRY/py-common:$PY_COMMON_COMMIT"
IMAGE="$REGISTRY/hww-job:<this project's commit from 5a>"

cd ~/py-common
docker build -t "$BASE_IMAGE" .
docker push "$BASE_IMAGE"

cd ~/hww_dashboard_poc
docker build --build-arg BASE_IMAGE="$BASE_IMAGE" -t "$IMAGE" .
docker push "$IMAGE"
```

Each push ends with a `digest: sha256:...` line when it works. A warning
that `ARG BASE_IMAGE` has no default is expected and harmless; the build
gets it from `--build-arg`. The HWW build ends by checking that the
code, py-common and the config load.

Check both arrived: `gcloud artifacts docker images list "$REGISTRY"`.

Remember `$IMAGE`: steps 6 and 10 use it. Afterwards, delete any zips you
copied through a bucket.

<details>
<summary>Alternative: build with Cloud Build instead of Cloud Shell</summary>

Cloud Build needs more permissions and often meets organisation
policies: a default `<project>_cloudbuild` bucket you may not be allowed
to use, and a build service account that needs read access to the
staging bucket, Artifact Registry Writer and Logs Writer. If those are in
place:

```bash
STAGING="gs://<bucket the build account can read>/cloudbuild-source"
cd ~/py-common
gcloud builds submit --project="$APP_PROJECT" \
  --config="$HOME/hww_dashboard_poc/cloudbuild.py-common.yaml" \
  --substitutions="_IMAGE=$BASE_IMAGE" --gcs-source-staging-dir="$STAGING" .
cd ~/hww_dashboard_poc
gcloud builds submit --project="$APP_PROJECT" --config=cloudbuild.yaml \
  --substitutions="_BASE_IMAGE=$BASE_IMAGE,_IMAGE=$IMAGE" \
  --gcs-source-staging-dir="$STAGING" .
```

Add `--service-account="projects/$APP_PROJECT/serviceAccounts/<account>"`
to build as a service account of your choice. (Those two build files
are in the HWW repository, so the full repository is needed for this
route, not the reduced zip.)
</details>

## 6. Create the daily job (Cloud Shell)

```bash
gcloud run jobs deploy "$JOB" \
  --project="$APP_PROJECT" --region="$REGION" --image="$IMAGE" \
  --service-account="$SA" --tasks=1 --max-retries=0 \
  --set-env-vars="HWW_GCP_PROJECT=$DATA_PROJECT,HWW_LANDING_BUCKET=$LANDING_BUCKET,HWW_STORE_BUCKET=$STORE_BUCKET,HWW_LANDED_DATASET=$DATASET,HWW_BQ_PROJECT=$DATA_PROJECT,HWW_BQ_DATASET=$REPORT_DATASET"
```

If the prompt changes to `>` and waits, a quote didn't close when
pasting: press Ctrl+C and paste it again as one line.

The job runs in the app project; the six variables all point at the
**data** project's buckets and datasets. The image runs `hww-run
/app/config.gcp.toml`, which is `config.toml` with only these locations
changed. Every variable must have a value, or the job stops naming the
one that's missing. Check them with:

```bash
gcloud run jobs describe "$JOB" --project="$APP_PROJECT" --region="$REGION" \
  --format="yaml(spec.template.spec.template.spec.containers[0].env)"
```

and fix one with
`gcloud run jobs update "$JOB" --project="$APP_PROJECT" --region="$REGION" --update-env-vars="NAME=value"`.

`--max-retries=0`: a rerun is safe (loaded files are skipped), but it
should be deliberate.

## 7. Run it once by hand (Cloud Shell)

```bash
gcloud run jobs execute "$JOB" --project="$APP_PROJECT" --region="$REGION" --wait
```

Then check:

- the execution succeeded (console: Cloud Run → Jobs → the job →
  Executions, where the logs are too);
- `hww_landed` has the four typed tables and today's rows in `audit`;
- `hww_reporting` has the reporting tables (`dim_employer`,
  `fact_engagement`, ...) and a `runs` row.

In the logs, lines from `ktd watcher`, `KRSI` and similar are Google's
own security monitoring and can be ignored. The pipeline's lines say what
it did; one starting `Stopped:` says why it stopped.

## 8. Schedule it (Cloud Shell)

If you have Cloud Scheduler Admin (otherwise Data Engineering can run
this):

```bash
gcloud scheduler jobs create http hww-daily-0600 \
  --project="$APP_PROJECT" --location="$REGION" \
  --schedule="0 6 * * *" --time-zone="Europe/London" \
  --http-method=POST \
  --uri="https://run.googleapis.com/v2/projects/$APP_PROJECT/locations/$REGION/jobs/$JOB:run" \
  --oauth-service-account-email="$SA"
```

6am every day. Daily rather than monthly, so a late or corrected upload
is picked up the next morning; a run with nothing new costs almost
nothing.

## 9. Alerts (console)

At minimum, alert on failures, so a quarantined workbook or a missing
folder doesn't go unnoticed. The logs are structured JSON, so log-based
alerts can match their fields. In the console: Logging → Logs Explorer,
enter a filter, then **Create alert** to the team's channel:

- `severity>=ERROR`: a failed or quarantined file, or a stopped run;
- `jsonPayload.message:"quarantined"`: a workbook rejected by its
  contract;
- `jsonPayload.message:"Report needs attention:"`: the data quality
  report has something to look at.

## 10. Optional: load within a minute of an upload

```
workbook uploaded to the landing bucket (data project)
  -> bucket notification to a Pub/Sub topic (app project)
  -> Eventarc trigger
  -> Cloud Run service (app project), same image as the daily job:
     ingests the folder the file landed in, then, if nothing was
     quarantined, rebuilds the reporting tables
```

**Keep the daily job.** Pub/Sub can drop an event (for example if the
service is down for over a day), and the daily run loads anything
missed. The two don't get in each other's way:

- **One load at a time.** Both take py-common's lock in the store
  bucket; whichever is refused tries again (Pub/Sub resends the event,
  the job runs tomorrow).
- **Nothing loads twice.** A file already loaded is skipped.
- **Rebuilding is repeatable.** The tables come from the newest load of
  every source, so rebuilding twice gives the same tables.
- **A quarantined file stops the rebuild,** so the reporting tables keep
  the last complete set.

When the four workbooks arrive at different times, each upload rebuilds
the tables, so for a while they mix this month's file for one source
with last month's for another. The daily job does the same. Uploading
all four together avoids it.

**10a. Deploy the service** (you, Cloud Shell):

```bash
gcloud run deploy "$SERVICE" \
  --project="$APP_PROJECT" --region="$REGION" --image="$IMAGE" \
  --service-account="$SA" --no-allow-unauthenticated \
  --max-instances=1 --concurrency=1 --timeout=540 \
  --command="functions-framework" \
  --args="--source=/app/src/hww_dashboard/service.py,--target=on_upload,--signature-type=cloudevent" \
  --set-env-vars="HWW_GCP_PROJECT=$DATA_PROJECT,HWW_LANDING_BUCKET=$LANDING_BUCKET,HWW_STORE_BUCKET=$STORE_BUCKET,HWW_LANDED_DATASET=$DATASET,HWW_BQ_PROJECT=$DATA_PROJECT,HWW_BQ_DATASET=$REPORT_DATASET"
```

| Setting | Why |
|---|---|
| `--max-instances=1 --concurrency=1` | One upload at a time: when four files land together, later events wait rather than being refused by the lock. |
| `--timeout=540` | Below the 600-second acknowledgement deadline, so a long run isn't resent while still going. |
| `--no-allow-unauthenticated` | Only Eventarc, as the pipeline service account, can call it. |

**10b. Ask for the trigger** (Data Engineering): tell them the service
is deployed, so they can set up the upload trigger ("What the admin
sets up": topic, bucket
notification, Eventarc trigger, acknowledgement deadline).

**10c. Check it works:**

1. Upload a workbook again to its folder.
2. Console: Cloud Run → Services → `hww-on-upload` → Logs. Within a
   minute or so: `Upload gs://...: running ...`, then
   `Upload handled: rebuilt`.
3. Upload any file to a folder with no pipeline, e.g. `hww/test/`: the
   logs say `Ignoring upload` and `Upload handled: ignored`.

| Event | Result |
|---|---|
| New file in a source's folder | That folder is ingested, then the tables are rebuilt |
| The same event delivered again | Files skipped as already loaded; tables rebuilt again, same result |
| A file is quarantined | Tables not rebuilt; ERROR logged; not retried |
| The rebuild stops on something to fix (a mapping, a setting) | ERROR logged; not retried |
| A file fails, the lock is held, or BigQuery fails | Retried by Pub/Sub |
| Upload to another folder or bucket, or a delete | Ignored |

For alerts (step 9) to cover the service as well as the job, include
both `resource.type="cloud_run_job"` and
`resource.type="cloud_run_revision"` in the filters.

## 11. Moving from a test set-up (Cloud Shell)

If you first ran this in one project, or with other buckets and
datasets:

1. Once the set-up is done, run steps 1, 5, 6 and 7 with the new names:
   rebuild the images into the app project's `hww` repository, create the
   job in the app project, and run it. (You can reuse the existing
   workbooks: upload them to the new landing bucket.)
2. When it works, delete the old job:
   `gcloud run jobs delete <old job> --project=<old project> --region="$REGION"`.
3. Ask the admin to remove the access given in the old project for this,
   and, if those buckets and datasets stay in use for other things, the
   pipeline's copies there (`raw/`, `processed/`, `quarantine/`,
   `audit/`, `locks/`) and its `hww_*` and `audit` tables.

## Updating

- **Code, config or mapping change:** commit it, rebuild this project's
  image (step 5, tag it with the new commit) and deploy it: step 6 again
  for the job, step 10a for the service.
- **py-common change:** update the commit pinned in `pyproject.toml`,
  rebuild both images, and deploy.

## When something goes wrong

| What you see | What to do |
|---|---|
| `Stopped: config.gcp.toml uses environment variable(s) that aren't set: [...]` | A variable was blank when the job was deployed. Fix it with `gcloud run jobs update ... --update-env-vars="NAME=value"` (step 6). |
| `quarantined` with a column name | The workbook doesn't match its contract: a new or missing column, or a value of the wrong type. Fix the workbook and upload again, or, if the change is intended, update the contract in `src/hww_dashboard/landing.py` and the matching `config.toml` setting, then rebuild. The file is kept in `gs://<store bucket>/quarantine/`. |
| `quarantined ... wrong file name, expected ...` | Uploaded under the wrong name. Delete it from the landing folder and upload it under the name in `config.toml`. |
| `no files in its landing folder` | Nothing in `hww/<source>/`. Check the folder names. |
| `403`, `Permission denied`, `Access Denied` | A role from "What the admin sets up" is missing. The message names the account and what it couldn't do; send that to the admin. |
| `Not found: Table ... audit` | The `audit` table hasn't been created (step 1b). |
| `docker push`: permission denied | You need Artifact Registry Writer on the `hww` repository. |
| Cloud Build errors about `<project>_cloudbuild`, logs or staging | Build in Cloud Shell instead (step 5). |
| A run is refused because of a lock | A previous run was stopped. Wait an hour for the lock to expire, or check nothing is running and delete the lock object named in the error. |
| The pipeline says "No landed table" or "no rows" | Ingestion hasn't loaded anything yet; check the job's earlier log lines and the landing folders. |

py-common's `docs/RUNBOOK.md` covers reloading, undoing a bad load and
renaming a workbook.
