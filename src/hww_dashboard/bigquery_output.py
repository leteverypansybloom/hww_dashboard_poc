"""Load the output tables into BigQuery, all or nothing.

Until the Dataform models exist, the pipeline's tables live in an
interim BigQuery dataset (``DECISIONS_en.md``, 2026-10-18).
:func:`publish` replaces all of them in one go:

1. Check the dataset exists, and that each final table has the schema
   in ``hww_dashboard/schema/``; create a table that is missing.
2. Load every table, the report and the run record into staging tables
   of this run's own, as newline-delimited JSON typed by the schema. A
   staging table expires after a day if a run dies before dropping it.
3. Run one script: in a single transaction, empty each final table and
   copy its staging table in, then append the run record to ``runs``.
   On any error the transaction rolls back and every table keeps its
   previous rows.
4. Drop the staging tables.

The tables come in as the CSV text the folder writer would write
(``wrangle.csv_text``), so the two writers publish the same rows.

BigQuery's error messages can quote the data that failed, so errors
are reported by type, status and reason, with the job id for
``bq show -j``, as in py-common's adapters.
"""

import io
import json
import logging
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from google.api_core.exceptions import (
    Forbidden,
    GoogleAPICallError,
    NotFound,
)
from google.auth.exceptions import DefaultCredentialsError
from google.cloud import bigquery

from hww_dashboard.output_schema import (
    BIGQUERY_FOLDER,
    Field,
    parse_csv,
    schema,
)

logger = logging.getLogger(__name__)

#: Seconds to wait for one BigQuery job before checking on it.
JOB_TIMEOUT_SECONDS = 600.0
#: How long a staging table lives if its run never drops it.
STAGING_LIFETIME = timedelta(days=1)
#: The table of run records, which only ever grows.
RUNS = "runs"
#: The data quality report, one row, replaced with the tables.
REPORT = "data_quality_report"
#: Legacy type names BigQuery reports for some standard SQL types.
TYPE_NAMES = {"INTEGER": "INT64", "BOOLEAN": "BOOL", "FLOAT": "FLOAT64"}


class BigQueryError(Exception):
    """BigQuery failed in a way a person can't fix from the message.

    ``python wrangle.py`` treats it as an unexpected error (exit code 2).
    The message names the job, never data.
    """


class PublishSetupError(Exception):
    """A problem a person can fix: access, a missing dataset, a schema.

    ``wrangle.run`` turns it into an ``InputError`` (exit code 1).
    """


def describe_error(error: BaseException) -> str:
    """Name a Google API failure without its free-text message.

    Args:
        error: The exception.

    Returns:
        For example ``Forbidden 403 (accessDenied)``: the type, status
        and reasons, which never hold data, but not the message, which
        can.
    """
    if isinstance(error, GoogleAPICallError):
        reasons = sorted(
            {
                str(detail["reason"])
                for detail in (error.errors or [])
                if isinstance(detail, dict) and detail.get("reason")
            }
        )
        code = f" {error.code}" if error.code else ""
        detail = f" ({', '.join(reasons)})" if reasons else ""
        return f"{type(error).__name__}{code}{detail}"
    return type(error).__name__


def schema_fields(fields: Iterable[Field]) -> list[bigquery.SchemaField]:
    """Turn a table's schema into BigQuery's own field objects.

    Args:
        fields: From :func:`hww_dashboard.output_schema.schema`.

    Returns:
        One ``SchemaField`` per column, in order.
    """
    return [
        bigquery.SchemaField(
            f.name, f.type, mode=f.mode, description=f.description
        )
        for f in fields
    ]


def json_value(text: str, field_type: str) -> Any:
    """Convert one CSV cell to the JSON value BigQuery loads.

    Args:
        text: The cell, as text; empty means NULL.
        field_type: The column's type.

    Returns:
        None for an empty cell, a bool for BOOL, an int for INT64, and
        the text itself for STRING, DATE and TIMESTAMP.
    """
    if text == "":
        return None
    if field_type == "BOOL":
        return text == "True"
    if field_type == "INT64":
        return int(text)
    return text


def ndjson(rows: Iterable[Mapping[str, Any]]) -> bytes:
    """Write rows as newline-delimited JSON.

    Args:
        rows: One mapping per row.

    Returns:
        UTF-8 bytes, one JSON object per line.
    """
    return "".join(
        json.dumps(row, ensure_ascii=False) + "\n" for row in rows
    ).encode("utf-8")


def table_rows(text: str, fields: Iterable[Field]) -> list[dict[str, Any]]:
    """Turn a table's CSV text into typed rows for BigQuery.

    Args:
        text: The table as CSV text.
        fields: Its schema.

    Returns:
        One dict per row, keyed by column name.
    """
    cells = parse_csv(text)
    columns = [(f.name, f.type) for f in fields]
    return [
        {name: json_value(row[name], kind) for name, kind in columns}
        for row in cells.to_dict("records")
    ]


def run_rows(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Make the ``runs`` row for a run record.

    Args:
        record: The finished run record.

    Returns:
        One row, with the record as JSON text.
    """
    code = record.get("code", {})
    return [
        {
            "run_id": record["run_id"],
            "started_at": record["started_at"],
            "finished_at": record["finished_at"],
            "outcome": record["outcome"],
            "git_commit": code.get("git_commit"),
            "package_version": code.get("version"),
            "record": json.dumps(record, ensure_ascii=False, sort_keys=True),
        }
    ]


def staging_suffix(run_id: str) -> str:
    """Make a table-name suffix from a run id.

    Args:
        run_id: The run's id.

    Returns:
        ``stg_`` and the id, lower case, with anything but letters,
        digits and underscores replaced by underscores.
    """
    return "stg_" + re.sub(r"[^0-9a-z_]", "_", run_id.lower())


def same_schema(
    found: Iterable[bigquery.SchemaField], wanted: Iterable[Field]
) -> bool:
    """Compare a table's columns in BigQuery with its schema file.

    Args:
        found: The table's schema, as BigQuery reports it.
        wanted: The schema file's fields.

    Returns:
        True if names, order, types and modes all match.
    """
    have = [
        (f.name, TYPE_NAMES.get(f.field_type, f.field_type), f.mode)
        for f in found
    ]
    return have == [(f.name, f.type, f.mode) for f in wanted]


def commit_script(
    dataset: str, columns: Mapping[str, list[str]], suffix: str
) -> str:
    """Build the script that swaps every table in one transaction.

    Args:
        dataset: ``project.dataset``.
        columns: Table -> column names. The value for a table that only
            needs emptying (a switched-off free-text table) is empty.
            ``runs`` is appended to, never emptied.
        suffix: The staging tables' suffix, from :func:`staging_suffix`.

    Returns:
        A BigQuery script. Any error rolls the transaction back, so no
        table changes, and is raised again.
    """
    lines = ["BEGIN", "  BEGIN TRANSACTION;"]
    for table, names in columns.items():
        final = f"`{dataset}.{table}`"
        if table != RUNS:
            lines.append(f"  DELETE FROM {final} WHERE TRUE;")
        if names:
            listed = ", ".join(names)
            staging = f"`{dataset}.{table}_{suffix}`"
            lines.append(
                f"  INSERT INTO {final} ({listed}) "
                f"SELECT {listed} FROM {staging};"
            )
    lines += [
        "  COMMIT TRANSACTION;",
        "EXCEPTION WHEN ERROR THEN",
        "  ROLLBACK TRANSACTION;",
        "  RAISE USING MESSAGE = @@error.message;",
        "END;",
    ]
    return "\n".join(lines)


def make_client(project: str, location: str | None = None) -> Any:
    """Create a BigQuery client with the account the run has.

    Args:
        project: The GCP project.
        location: The dataset's location, e.g. ``europe-west2``.

    Returns:
        A ``google.cloud.bigquery.Client``.

    Raises:
        PublishSetupError: No Google credentials were found.
    """
    try:
        return bigquery.Client(project=project, location=location)
    except DefaultCredentialsError:
        raise PublishSetupError(
            "No Google credentials. On a laptop, run "
            "gcloud auth application-default login; in GCP, the job's "
            "service account is used (docs/gcp.md)."
        ) from None


def ensure_table(
    client: Any, table_id: str, fields: tuple[Field, ...]
) -> bool:
    """Make sure a final table exists, with the schema it should have.

    Args:
        client: BigQuery client.
        table_id: ``project.dataset.table``.
        fields: The table's schema.

    Returns:
        True if the table was there already, False if it was created.

    Raises:
        PublishSetupError: The table exists with different columns.
    """
    try:
        table = client.get_table(table_id)
    except NotFound:
        client.create_table(
            bigquery.Table(table_id, schema=schema_fields(fields))
        )
        logger.info("Created BigQuery table %s", table_id)
        return False
    if not same_schema(table.schema, fields):
        raise PublishSetupError(
            f"BigQuery table {table_id} has different columns from its "
            "schema in hww_dashboard/schema/. A schema change needs the "
            "table replaced on purpose (docs/gcp.md)."
        )
    return True


def wait(job: Any, what: str, timeout: float) -> None:
    """Wait for a BigQuery job, checking its state if waiting fails.

    Args:
        job: A load or query job.
        what: What the job is for, for messages.
        timeout: Seconds to wait.

    Raises:
        BigQueryError: The job failed, or its outcome is unknown.
    """
    try:
        job.result(timeout=timeout)
        return
    except Exception as error:
        failure = error
    try:
        job.reload()
    except Exception:
        raise BigQueryError(
            f"BigQuery job {job.job_id} for {what}: waiting failed "
            f"({describe_error(failure)}) and its state is unknown. Check "
            f"bq show -j {job.job_id}."
        ) from None
    if job.state == "DONE" and job.error_result is None:
        return
    raise BigQueryError(
        f"BigQuery job {job.job_id} failed for {what} "
        f"({describe_error(failure)}); details: bq show -j {job.job_id}"
    ) from None


def latest_record(
    dataset: str, client: Any, timeout: float = JOB_TIMEOUT_SECONDS
) -> dict[str, Any] | None:
    """Read the most recent run record from the ``runs`` table.

    Args:
        dataset: ``project.dataset``.
        client: A BigQuery client.
        timeout: Seconds to wait for the query.

    Returns:
        The record, or None before the first run (no ``runs`` table or
        no rows yet).

    Raises:
        PublishSetupError: BigQuery refused access.
        BigQueryError: Any other BigQuery failure.
    """
    sql = (
        f"SELECT record FROM `{dataset}.{RUNS}` "
        "ORDER BY finished_at DESC LIMIT 1"
    )
    try:
        rows = list(client.query(sql).result(timeout=timeout))
    except NotFound:
        return None
    except Forbidden as error:
        raise PublishSetupError(
            f"BigQuery refused access to {dataset} ({describe_error(error)})."
            " The account running the pipeline needs BigQuery Data Editor "
            "on the dataset and BigQuery Job User on the project "
            "(docs/gcp.md)."
        ) from None
    except GoogleAPICallError as error:
        raise BigQueryError(
            f"BigQuery failed reading the last run from {dataset} "
            f"({describe_error(error)})."
        ) from None
    if not rows:
        return None
    data = json.loads(rows[0][0])
    return data if isinstance(data, dict) else None


def publish(
    tables: Mapping[str, str],
    report: str,
    record: Mapping[str, Any],
    dataset: str,
    client: Any,
    timeout: float = JOB_TIMEOUT_SECONDS,
) -> None:
    """Replace the output tables in BigQuery, all or nothing.

    Args:
        tables: Table name -> its CSV text, from ``wrangle.csv_text``.
        report: The data quality report, as markdown.
        record: The finished run record.
        dataset: ``project.dataset`` to publish to.
        client: A BigQuery client (from :func:`make_client`, or a fake
            in the tests).
        timeout: Seconds to wait for each BigQuery job.

    Raises:
        PublishSetupError: Access was refused, the dataset doesn't exist,
            or a table's columns differ from its schema. A person can
            fix these.
        BigQueryError: Any other BigQuery failure. No table changes,
            unless the final job's outcome is unknown, which the message
            says.
    """
    try:
        _publish(tables, report, record, dataset, client, timeout)
    except Forbidden as error:
        raise PublishSetupError(
            f"BigQuery refused access to {dataset} ({describe_error(error)})."
            " The account running the pipeline needs BigQuery Data Editor "
            "on the dataset and BigQuery Job User on the project "
            "(docs/gcp.md)."
        ) from None
    except GoogleAPICallError as error:
        raise BigQueryError(
            f"BigQuery failed while publishing to {dataset} "
            f"({describe_error(error)})."
        ) from None


def _publish(
    tables: Mapping[str, str],
    report: str,
    record: Mapping[str, Any],
    dataset: str,
    client: Any,
    timeout: float,
) -> None:
    """Do the work of :func:`publish`, letting Google errors through.

    Args:
        tables: Table name -> its CSV text.
        report: The data quality report.
        record: The finished run record.
        dataset: ``project.dataset``.
        client: A BigQuery client.
        timeout: Seconds to wait for each job.

    Raises:
        PublishSetupError: The dataset is missing, or a table's columns
            differ from its schema.
    """
    try:
        client.get_dataset(dataset)
    except NotFound:
        raise PublishSetupError(
            f"BigQuery dataset {dataset} doesn't exist. Create it first "
            "(docs/gcp.md)."
        ) from None
    loads: dict[str, tuple[tuple[Field, ...], list[dict[str, Any]]]] = {}
    for name, text in tables.items():
        fields = schema(name)
        loads[name] = (fields, table_rows(text, fields))
    report_fields = schema(REPORT, BIGQUERY_FOLDER)
    loads[REPORT] = (
        report_fields,
        [{"run_id": record["run_id"], "report": report}],
    )
    loads[RUNS] = (schema(RUNS, BIGQUERY_FOLDER), run_rows(record))

    columns: dict[str, list[str]] = {}
    for name, (fields, _rows) in loads.items():
        ensure_table(client, f"{dataset}.{name}", fields)
        columns[name] = [f.name for f in fields]
    if "survey_other_text" not in tables:
        # Free text switched off: empty the table if an earlier run
        # wrote it, in the same transaction.
        try:
            client.get_table(f"{dataset}.survey_other_text")
        except NotFound:
            pass
        else:
            columns = {"survey_other_text": [], **columns}

    suffix = staging_suffix(str(record["run_id"]))
    staged: list[str] = []
    try:
        for name, (fields, rows) in loads.items():
            staging_id = f"{dataset}.{name}_{suffix}"
            table = bigquery.Table(staging_id, schema=schema_fields(fields))
            table.expires = datetime.now(UTC) + STAGING_LIFETIME
            client.create_table(table)
            staged.append(staging_id)
            config = bigquery.LoadJobConfig(
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                schema=schema_fields(fields),
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            )
            job = client.load_table_from_file(
                io.BytesIO(ndjson(rows)), staging_id, job_config=config
            )
            wait(job, f"staging {name}", timeout)
        job = client.query(commit_script(dataset, columns, suffix))
        logger.info("Publishing to %s: BigQuery job %s", dataset, job.job_id)
        wait(job, f"publishing to {dataset}", timeout)
    finally:
        for staging_id in staged:
            try:
                client.delete_table(staging_id, not_found_ok=True)
            except Exception as error:
                logger.warning(
                    "Could not drop staging table %s (it expires by "
                    "itself): %s",
                    staging_id,
                    describe_error(error),
                )
    logger.info(
        "Published %d tables, the report and the run record to %s",
        len(tables),
        dataset,
    )
