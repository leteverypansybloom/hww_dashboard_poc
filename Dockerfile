# The HWW job image: py-common ingestion, then the pipeline.
#
# The daily Cloud Run job runs the default command: `hww-run
# /app/config.gcp.toml` loads every folder of the landing bucket into
# raw BigQuery tables with py-common, then, if every file loaded,
# builds the reporting tables.
#
# It builds FROM py-common's own image (its Dockerfile), which already
# has py-common[gcp] installed at its pinned versions, so this build
# needs no access to py-common's GitHub repository. Build that image
# first and pass its URI as BASE_IMAGE; docs/gcp_ingestion.md has the
# steps (cloudbuild.yaml builds this image in GCP, no local Docker).

ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ARG HWW_GIT_COMMIT
ARG PY_COMMON_VERSION=0.5.0

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HWW_LOG_FORMAT=json \
    HWW_GIT_COMMIT=${HWW_GIT_COMMIT}

# The base image ends as its unprivileged user; installing needs root.
USER root
WORKDIR /app

# The package, with the BigQuery output extra, at the versions in
# constraints.txt. py-common comes from the base
# image, so the landing extra (a GitHub install) isn't asked for.
COPY pyproject.toml constraints.txt README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir --constraint constraints.txt \
        ".[bigquery]" && \
    pip check
RUN python -c "import importlib.metadata as m, re; from py_common import GraphJsonLinesContract; assert m.version('py-common') == '${PY_COMMON_VERSION}'; assert re.fullmatch('[0-9a-f]{40}', '${HWW_GIT_COMMIT}'), 'Pass the reviewed HWW commit as HWW_GIT_COMMIT'"

# The settings and mappings the job runs with.
COPY config.gcp.toml config.gcp.dummy.toml ./
COPY mappings ./mappings

# Check the code and both libraries load, and the config is readable
# (its ${NAME} values are filled in at run time, so only parse it).
RUN python -c "import tomllib, hww_dashboard.job, py_common.adapters.bigquery_raw; tomllib.load(open('/app/config.gcp.toml', 'rb')); print('hww job image ready')"

# Back to the base image's unprivileged user.
USER app

CMD ["hww-run", "/app/config.gcp.toml"]
