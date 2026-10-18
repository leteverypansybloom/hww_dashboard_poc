"""Checks on the BigQuery writer, against a fake BigQuery client.

The fake keeps tables in memory and runs the writer's commit script by
applying its DELETE and INSERT statements to a copy of them, which it
keeps only if every statement succeeds, as BigQuery's transaction
would. A live test against a real dataset runs only when
HWW_BQ_TEST_PROJECT and HWW_BQ_TEST_DATASET are set.
"""

import copy
import json
import os
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from google.api_core.exceptions import BadRequest, Forbidden, NotFound
from google.cloud import bigquery

from hww_dashboard import bigquery_output
from hww_dashboard.output_schema import BIGQUERY_FOLDER, schema

GOLDEN = Path(__file__).resolve().parent / "golden"
DATASET = "proj.hww_interim"


class FakeJob:
    """A finished BigQuery job, failed or not."""

    def __init__(self, job_id: str, error: Exception | None = None) -> None:
        """Remember the job's id and its error, if any.

        Args:
            job_id: The job id.
            error: What waiting for the job raises.
        """
        self.job_id = job_id
        self.error = error
        self.state = "DONE"
        self.error_result = None if error is None else {"reason": "invalid"}

    def result(self, timeout: float | None = None) -> list[Any]:
        """Wait for the job.

        Args:
            timeout: Ignored.

        Returns:
            No rows.

        Raises:
            Exception: The job's error.
        """
        if self.error is not None:
            raise self.error
        return []

    def reload(self) -> None:
        """Re-read the job's state; it never changes here."""


class FakeClient:
    """The parts of ``bigquery.Client`` the writer uses, in memory.

    Attributes:
        datasets: Datasets that exist.
        tables: Table id -> {"schema": fields, "rows": rows}.
        fail_insert_into: A table whose INSERT fails in the commit.
        queries: Every script run.
    """

    def __init__(self) -> None:
        """Start with one empty dataset."""
        self.datasets = {DATASET}
        self.tables: dict[str, dict[str, Any]] = {}
        self.fail_insert_into: str | None = None
        self.queries: list[str] = []
        self.jobs = 0

    def job_id(self) -> str:
        """Number the next job.

        Returns:
            A job id.
        """
        self.jobs += 1
        return f"job_{self.jobs}"

    def get_dataset(self, dataset: str) -> object:
        """Return a dataset that exists.

        Args:
            dataset: ``project.dataset``.

        Returns:
            Anything.

        Raises:
            NotFound: The dataset doesn't exist.
        """
        if dataset not in self.datasets:
            raise NotFound("dataset")
        return object()

    def get_table(self, table_id: str) -> SimpleNamespace:
        """Return a table's schema.

        Args:
            table_id: ``project.dataset.table``.

        Returns:
            An object with a ``schema``.

        Raises:
            NotFound: The table doesn't exist.
        """
        if table_id not in self.tables:
            raise NotFound("table")
        return SimpleNamespace(schema=self.tables[table_id]["schema"])

    def create_table(self, table: bigquery.Table) -> None:
        """Create an empty table.

        Args:
            table: The table to create.
        """
        table_id = f"{table.project}.{table.dataset_id}.{table.table_id}"
        self.tables[table_id] = {"schema": list(table.schema), "rows": []}

    def load_table_from_file(
        self, file: Any, table_id: str, job_config: Any
    ) -> FakeJob:
        """Replace a table's rows with newline-delimited JSON.

        Args:
            file: The JSON lines.
            table_id: The table to load.
            job_config: Ignored.

        Returns:
            A finished job.
        """
        names = {f.name for f in self.tables[table_id]["schema"]}
        rows = [json.loads(line) for line in file.read().splitlines()]
        for row in rows:
            assert set(row) <= names, set(row) - names
        self.tables[table_id]["rows"] = rows
        return FakeJob(self.job_id())

    def query(self, script: str) -> FakeJob:
        """Run the writer's commit script as one transaction.

        Args:
            script: The script.

        Returns:
            A finished job, failed if an INSERT was made to fail.
        """
        self.queries.append(script)
        work = copy.deepcopy(self.tables)
        for table_id in re.findall(
            r"DELETE FROM `([^`]+)` WHERE TRUE;", script
        ):
            work[table_id]["rows"] = []
        inserts = re.findall(
            r"INSERT INTO `([^`]+)` \(([^)]*)\) SELECT [^;]+ FROM `([^`]+)`;",
            script,
        )
        for final, listed, staging in inserts:
            if final == self.fail_insert_into:
                return FakeJob(self.job_id(), BadRequest("insert failed"))
            names = [n.strip() for n in listed.split(",")]
            work[final]["rows"] += [
                {n: row.get(n) for n in names} for row in work[staging]["rows"]
            ]
        self.tables = work
        return FakeJob(self.job_id())

    def delete_table(self, table_id: str, not_found_ok: bool = False) -> None:
        """Drop a table.

        Args:
            table_id: The table.
            not_found_ok: Ignored; missing tables are fine.
        """
        self.tables.pop(table_id, None)

    def rows(self, table: str) -> list[dict[str, Any]]:
        """Read a final table's rows.

        Args:
            table: Table name.

        Returns:
            Its rows.
        """
        rows: list[dict[str, Any]] = self.tables[f"{DATASET}.{table}"]["rows"]
        return rows


def golden_tables() -> dict[str, str]:
    """Read the snapshot tables as the CSV text the writer receives.

    Returns:
        Table name -> CSV text.
    """
    return {
        path.stem: path.read_text("utf-8").replace("\r\n", "\n")
        for path in sorted(GOLDEN.glob("*.csv"))
    }


def record(run_id: str) -> dict[str, Any]:
    """Make a small run record.

    Args:
        run_id: The run's id.

    Returns:
        A record with the fields the ``runs`` table needs.
    """
    return {
        "run_id": run_id,
        "started_at": "2026-10-10T11:00:00+00:00",
        "finished_at": "2026-10-10T11:00:05+00:00",
        "outcome": "published",
        "code": {"version": "0.1.0", "git_commit": "abc123"},
    }


@pytest.fixture
def client() -> FakeClient:
    """A fake BigQuery with an empty dataset.

    Returns:
        The fake client.
    """
    return FakeClient()


class TestPublish:
    """``publish``: replace every table at once, or none of them."""

    def test_first_run_creates_and_fills_every_table(
        self, client: FakeClient
    ) -> None:
        """Tables are created from their schemas and hold every row.

        Args:
            client: A fake BigQuery.
        """
        tables = golden_tables()
        bigquery_output.publish(
            tables, "# Report", record("run-1"), DATASET, client
        )
        for name, text in tables.items():
            assert len(client.rows(name)) == text.count("\n") - 1, name
        assert client.rows("data_quality_report") == [
            {"run_id": "run-1", "report": "# Report"}
        ]
        [run] = client.rows("runs")
        assert run["run_id"] == "run-1"
        assert json.loads(run["record"])["outcome"] == "published"
        assert not [t for t in client.tables if "_stg_" in t]

    def test_values_are_typed_by_the_schema(self, client: FakeClient) -> None:
        """BOOL, INT64 and empty cells load as JSON true, 7 and null.

        Args:
            client: A fake BigQuery.
        """
        bigquery_output.publish(
            golden_tables(), "# Report", record("run-1"), DATASET, client
        )
        employer = client.rows("dim_employer")[0]
        assert employer["in_signups"] in (True, False)
        assert isinstance(client.rows("dim_date")[0]["year"], int)
        unlinked = [
            r for r in client.rows("fact_engagement") if not r["employer_id"]
        ]
        assert unlinked and unlinked[0]["employer_id"] is None

    def test_a_second_run_replaces_tables_and_adds_a_run(
        self, client: FakeClient
    ) -> None:
        """Tables hold one run's rows; ``runs`` keeps every run.

        Args:
            client: A fake BigQuery.
        """
        tables = golden_tables()
        for run_id in ("run-1", "run-2"):
            bigquery_output.publish(
                tables, run_id, record(run_id), DATASET, client
            )
        assert len(client.rows("dim_date")) == 730
        assert [r["run_id"] for r in client.rows("runs")] == [
            "run-1",
            "run-2",
        ]
        assert client.rows("data_quality_report")[0]["report"] == "run-2"

    def test_a_failed_commit_changes_nothing(self, client: FakeClient) -> None:
        """A failure mid-commit leaves every table as it was.

        Args:
            client: A fake BigQuery.
        """
        tables = golden_tables()
        bigquery_output.publish(
            tables, "first", record("run-1"), DATASET, client
        )
        before = copy.deepcopy(
            {t: v["rows"] for t, v in client.tables.items()}
        )
        client.fail_insert_into = f"{DATASET}.fact_engagement"
        changed = dict(tables, dim_date=tables["dim_date"].split("\n")[0])
        with pytest.raises(bigquery_output.BigQueryError, match="job_"):
            bigquery_output.publish(
                changed, "second", record("run-2"), DATASET, client
            )
        after = {t: v["rows"] for t, v in client.tables.items()}
        assert after == before

    def test_missing_dataset_is_a_problem_to_fix(
        self, client: FakeClient
    ) -> None:
        """A dataset that doesn't exist names itself and the fix.

        Args:
            client: A fake BigQuery.
        """
        client.datasets.clear()
        with pytest.raises(
            bigquery_output.PublishSetupError, match="Create it"
        ):
            bigquery_output.publish(
                golden_tables(), "", record("r"), DATASET, client
            )

    def test_refused_access_is_a_problem_to_fix(
        self, client: FakeClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Access refused says which roles the account needs.

        Args:
            client: A fake BigQuery.
            monkeypatch: Makes the dataset check refuse access.
        """

        def refuse(dataset: str) -> object:
            """Refuse, as BigQuery does without the right role.

            Args:
                dataset: Ignored.

            Raises:
                Forbidden: Always.
            """
            raise Forbidden("Access Denied: secret detail")

        monkeypatch.setattr(client, "get_dataset", refuse)
        with pytest.raises(bigquery_output.PublishSetupError) as error:
            bigquery_output.publish(
                golden_tables(), "", record("r"), DATASET, client
            )
        assert "Data Editor" in str(error.value)
        assert "secret detail" not in str(error.value)

    def test_a_table_with_other_columns_is_refused(
        self, client: FakeClient
    ) -> None:
        """A table whose columns changed must be replaced on purpose.

        Args:
            client: A fake BigQuery.
        """
        client.create_table(
            bigquery.Table(
                f"{DATASET}.dim_employer",
                schema=[bigquery.SchemaField("employer_id", "STRING")],
            )
        )
        with pytest.raises(
            bigquery_output.PublishSetupError, match="different columns"
        ):
            bigquery_output.publish(
                golden_tables(), "", record("r"), DATASET, client
            )

    def test_switched_off_free_text_is_emptied(
        self, client: FakeClient
    ) -> None:
        """Free text from an earlier run goes when the option is off.

        Args:
            client: A fake BigQuery.
        """
        tables = golden_tables()
        with_text = dict(
            tables,
            survey_other_text="response_id,question_id,other_text\nR,Q,x\n",
        )
        bigquery_output.publish(with_text, "", record("r1"), DATASET, client)
        assert len(client.rows("survey_other_text")) == 1
        bigquery_output.publish(tables, "", record("r2"), DATASET, client)
        assert client.rows("survey_other_text") == []


class TestCommitScript:
    """``commit_script``: one transaction that rolls back on error."""

    def test_runs_is_appended_and_errors_roll_back(self) -> None:
        """Tables are emptied and refilled; runs only gets a row."""
        script = bigquery_output.commit_script(
            "p.d", {"dim_date": ["date"], "runs": ["run_id"]}, "stg_x"
        )
        assert "BEGIN TRANSACTION;" in script
        assert "DELETE FROM `p.d.dim_date` WHERE TRUE;" in script
        assert "DELETE FROM `p.d.runs`" not in script
        assert (
            "INSERT INTO `p.d.runs` (run_id) SELECT run_id FROM "
            "`p.d.runs_stg_x`;" in script
        )
        assert "ROLLBACK TRANSACTION;" in script


class TestJsonValue:
    """``json_value``: a CSV cell as the JSON BigQuery loads."""

    @pytest.mark.parametrize(
        ("text", "kind", "value"),
        [
            ("", "STRING", None),
            ("", "BOOL", None),
            ("True", "BOOL", True),
            ("False", "BOOL", False),
            ("12", "INT64", 12),
            ("2026-03-04", "DATE", "2026-03-04"),
            ("Org 1", "STRING", "Org 1"),
        ],
    )
    def test_cells(self, text: str, kind: str, value: object) -> None:
        """Each type converts as its schema says.

        Args:
            text: The cell.
            kind: The column's type.
            value: The expected JSON value.
        """
        assert bigquery_output.json_value(text, kind) == value


class TestSameSchema:
    """``same_schema``: BigQuery's legacy type names count as equal."""

    def test_legacy_names_match(self) -> None:
        """INTEGER and BOOLEAN are INT64 and BOOL."""
        fields = schema("dim_date")
        found = [
            bigquery.SchemaField(
                f.name,
                {"INT64": "INTEGER", "BOOL": "BOOLEAN"}.get(f.type, f.type),
                mode=f.mode,
            )
            for f in fields
        ]
        assert bigquery_output.same_schema(found, fields)

    def test_bigquery_only_tables_have_schemas(self) -> None:
        """The report and runs tables have schema files of their own."""
        for name in (bigquery_output.REPORT, bigquery_output.RUNS):
            assert schema(name, BIGQUERY_FOLDER)


class TestDescribeError:
    """``describe_error``: name a failure without its message."""

    def test_message_is_left_out(self) -> None:
        """The type and status are kept; the free text is not."""
        error = BadRequest("Could not parse 'Org 11' as INT64")
        described = bigquery_output.describe_error(error)
        assert described.startswith("BadRequest 400")
        assert "Org 11" not in described


LIVE = pytest.mark.skipif(
    not (
        os.environ.get("HWW_BQ_TEST_PROJECT")
        and os.environ.get("HWW_BQ_TEST_DATASET")
    ),
    reason="set HWW_BQ_TEST_PROJECT and HWW_BQ_TEST_DATASET to run",
)


@pytest.mark.integration
@LIVE
class TestPublishLive:
    """``publish`` against a real BigQuery test dataset."""

    def test_round_trip(self) -> None:
        """The golden tables load, and come back with every row."""
        project = os.environ["HWW_BQ_TEST_PROJECT"]
        dataset = f"{project}.{os.environ['HWW_BQ_TEST_DATASET']}"
        client = bigquery_output.make_client(project)
        tables = golden_tables()
        bigquery_output.publish(
            tables, "# Live test", record("live-test"), dataset, client
        )
        for name, text in tables.items():
            count = list(
                client.query(f"SELECT COUNT(*) FROM `{dataset}.{name}`")
            )[0][0]
            assert count == text.count("\n") - 1, name
