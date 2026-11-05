# GCP operation

Use [production operation](production.md) for the current GitHub schedule,
Graph exports, access model and acceptance requirements. A development Cloud
Run job has run with the combined image.

The maintained image runs hww-run with config.gcp.toml: generation-pinned
GCS ingestion, raw JSON loads, then the reporting rebuild. For image builds
and the legacy Cloud Run triggers, use [GCP ingestion](gcp_ingestion.md).
Do not deploy that image with workbook-mount commands: they describe a
different input route and do not use its ingestion contracts.

Keep development, production raw and production reporting resources separate.
Record the approved HWW commit, shared-library commit, image digest, config,
mapping checksums, source generations and output sign-off for each release.
BigQuery execution and Dataform acceptance remain required before cut-over.
