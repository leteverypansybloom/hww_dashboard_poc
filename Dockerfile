# The HWW job image: py-common ingestion, then the pipeline.
#
# Two ways to run it, from the same image:
# - the daily Cloud Run job (the default command): `hww-run
#   /app/config.gcp.toml` loads every folder of the landing bucket into
#   raw BigQuery tables with py-common, then, if every file loaded,
#   builds the reporting tables;
# - the upload-triggered Cloud Run service: functions-framework runs
#   hww_dashboard/service.py's on_upload, which does the same for the
#   folder a file was uploaded to (docs/gcp_ingestion.md, step 9).
#
# It builds FROM py-common's own image (its Dockerfile), which already
# has py-common[gcp] installed at its pinned versions, so this build
# needs no access to py-common's GitHub repository. Build that image
# first and pass its URI as BASE_IMAGE; docs/gcp_ingestion.md has the
# steps (cloudbuild.yaml builds this image in GCP, no local Docker).

ARG BASE_IMAGE
FROM ${BASE_IMAGE}

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HWW_LOG_FORMAT=json

# The base image ends as its unprivileged user; installing needs root.
USER root
WORKDIR /app

# The package, with the BigQuery output and Cloud Run service extras,
# at the versions in constraints.txt. py-common comes from the base
# image, so the landing extra (a GitHub install) isn't asked for.
COPY pyproject.toml constraints.txt README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir --constraint constraints.txt \
        ".[bigquery,service]" && \
    pip check

# The settings and mappings the job runs with.
COPY config.gcp.toml ./
COPY mappings ./mappings

# Check the code and both libraries load, and the config is readable
# (its ${NAME} values are filled in at run time, so only parse it).
RUN python -c "import tomllib, hww_dashboard.job, hww_dashboard.service, functions_framework, py_common.adapters.bigquery_raw; tomllib.load(open('/app/config.gcp.toml', 'rb')); print('hww job image ready')"

# Back to the base image's unprivileged user.
USER app

CMD ["hww-run", "/app/config.gcp.toml"]
