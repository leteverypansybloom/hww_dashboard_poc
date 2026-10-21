"""Checks on ingestion with py-common's typed route, and reading it back.

``python ingest.py`` lands the synthetic workbooks in local typed tables
(landing.py); ``wrangle.py`` with ``[landed] read = true`` reads them
back (landed.py). The end-to-end check runs both and compares every
table with the golden snapshot made from the workbooks directly.
"""

import json
import shutil
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from openpyxl import load_workbook

pytest.importorskip("py_common")

from py_common.errors import ServiceError, ValidationError  # noqa: E402
from py_common.model import Outcome, SourceItem  # noqa: E402
from py_common.parquet import column_name  # noqa: E402

from hww_dashboard import landed, landing, wrangle  # noqa: E402

GOLDEN = Path(__file__).resolve().parent / "golden"
WAS_FILE = "dummy_was_database.xlsx"


def landing_config(
    tmp_path: Path, data_folder: Path, read: bool, **landed_settings: str
) -> Path:
    """Write a config that lands and reads in tmp_path.

    Args:
        tmp_path: Folder for the config, landing folder, store, tables.
        data_folder: tests/data, whose config.toml is copied.
        read: The [landed] read setting.
        **landed_settings: More [landed] settings.

    Returns:
        The config file.
    """
    project = data_folder.parent.parent
    text = (data_folder / "config.toml").read_text(encoding="utf-8")
    inputs = (data_folder / "inputs").as_posix()
    maps = (project / "mappings").as_posix()
    text = text.replace(
        'input_folder = "inputs"', f'input_folder = "{inputs}"'
    )
    text = text.replace(
        'mappings_folder = "../../mappings"', f'mappings_folder = "{maps}"'
    )
    lines = [f"read = {'true' if read else 'false'}", 'target = "local"']
    lines += [f'{key} = "{value}"' for key, value in landed_settings.items()]
    text += "\n[landed]\n" + "\n".join(lines) + "\n"
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def settings_of(config: Path) -> wrangle.Config:
    """The config, loaded and checked as the pipeline loads it.

    Args:
        config: config.toml.

    Returns:
        Its settings.
    """
    return wrangle.load_config(config)


@pytest.fixture(scope="module")
def landed_run(
    tmp_path_factory: pytest.TempPathFactory, data_folder: Path
) -> Path:
    """Stage and land the synthetic workbooks once.

    Args:
        tmp_path_factory: For a folder shared by this module.
        data_folder: tests/data.

    Returns:
        The folder holding config.toml, landing/, store/ and landed/.
    """
    folder = tmp_path_factory.mktemp("landed")
    config = landing_config(folder, data_folder, read=True)
    results = landing.ingest(config, stage_from=data_folder / "inputs")
    text, ok = landing.summary(results)
    assert ok, text
    return folder


class TestContracts:
    """The HWW contracts accept the workbooks and keep personal data out."""

    def test_every_source_loads(self, landed_run: Path) -> None:
        """Each source's typed table has the workbook's data rows."""
        rows = {
            source: pq.read_table(
                landed_run / "landed" / f"{table}.parquet"
            ).num_rows
            for source, table in landing.TABLES.items()
        }
        assert rows == {"signups": 200, "survey": 1, "was": 35, "peer": 11}

    def test_personal_columns_are_not_loaded(
        self, landed_run: Path, data_folder: Path
    ) -> None:
        """No column named in [privacy] reaches a typed table."""
        cfg = settings_of(landed_run / "config.toml")
        personal = {column_name(c) for c in cfg["privacy"]["personal_columns"]}
        for table in landing.TABLES.values():
            names = set(
                pq.read_table(
                    landed_run / "landed" / f"{table}.parquet"
                ).column_names
            )
            assert not names & personal, table

    def test_typed_columns_keep_their_types(self, landed_run: Path) -> None:
        """Dates load as timestamps and the WAS id as a whole number."""
        schema = pq.read_schema(landed_run / "landed" / "hww_was.parquet")
        assert schema.field("date_of_enquiry").type == pa.timestamp("us")
        assert schema.field("participant_id").type == pa.int64()

    def test_every_config_column_is_in_its_contract(
        self, landed_run: Path
    ) -> None:
        """Each heading config.toml reads is a loaded column."""
        cfg = settings_of(landed_run / "config.toml")
        maps = Path(cfg["paths"]["mappings_folder"])
        contracts = landing.source_contracts(cfg, maps)
        for source in ("signups", "was", "peer"):
            known = set(contracts[source].names.values())
            needed = {
                value
                for key, value in cfg[source].items()
                if isinstance(value, str)
                and key not in ("file", "file_pattern", "sheet")
                and key not in ("completed_rule", "topic_separator")
            }
            if source == "was":
                needed |= {
                    value
                    for session in cfg["was"]["sessions"]
                    for key, value in session.items()
                    if key != "number"
                }
            assert needed <= known, (source, needed - known)

    def test_new_column_quarantines_the_file(
        self, tmp_path: Path, data_folder: Path
    ) -> None:
        """A column the WAS contract doesn't know stops the load."""
        config = landing_config(tmp_path, data_folder, read=False)
        landing.stage(
            settings_of(config), data_folder / "inputs", tmp_path / "landing"
        )
        book = tmp_path / "landing" / "was" / WAS_FILE
        workbook = load_workbook(book)
        sheet = workbook.active
        assert sheet is not None
        sheet.cell(row=1, column=sheet.max_column + 1, value="Home address")
        sheet.cell(row=2, column=sheet.max_column, value="1 High Street")
        workbook.save(book)

        results = landing.ingest(config)

        (was,) = results["was"]
        assert was.outcome == Outcome.QUARANTINED
        assert "Home address" in "; ".join(was.errors)
        assert not (tmp_path / "landed" / "hww_was.parquet").exists()

    def test_wrong_type_quarantines_the_file(
        self, tmp_path: Path, data_folder: Path
    ) -> None:
        """Text in a date column stops the load (schema checked)."""
        config = landing_config(tmp_path, data_folder, read=False)
        landing.stage(
            settings_of(config), data_folder / "inputs", tmp_path / "landing"
        )
        book = tmp_path / "landing" / "was" / WAS_FILE
        workbook = load_workbook(book)
        sheet = workbook.active
        assert sheet is not None
        sheet.cell(row=2, column=2, value="next Tuesday")
        workbook.save(book)

        (was,) = landing.ingest(config)["was"]

        assert was.outcome == Outcome.QUARANTINED

    def test_running_again_loads_nothing_twice(
        self, tmp_path: Path, data_folder: Path
    ) -> None:
        """A second run with the same files skips them."""
        config = landing_config(tmp_path, data_folder, read=False)
        landing.ingest(config, stage_from=data_folder / "inputs")

        again = landing.ingest(config)

        assert all(
            r.outcome == Outcome.SKIPPED for rs in again.values() for r in rs
        )
        table = pq.read_table(tmp_path / "landed" / "hww_peer.parquet")
        assert table.num_rows == 11


class TestRepeatedHeadings:
    """Headings convert between pandas' and py-common's numbering."""

    def test_round_trip(self) -> None:
        """Other.2 is py-common's Other_3, and back."""
        assert landing.py_common_name("Other.2") == "Other_3"
        assert landing.py_common_name("Other") == "Other"
        assert landing.pandas_name("col_B") == "B"
        assert landing.pandas_name("Organisation Industry ") == (
            "Organisation Industry"
        )


class TestLocalTableWarehouse:
    """The local stand-in follows py-common's Warehouse protocol."""

    @staticmethod
    def parquet(rows: int) -> bytes:
        """Parquet bytes with one text column.

        Args:
            rows: Number of rows.

        Returns:
            The bytes.
        """
        table = pa.table({"name": [f"Org {n}" for n in range(rows)]})
        sink = pa.BufferOutputStream()
        pq.write_table(table, sink)
        return bytes(sink.getvalue().to_pybytes())

    def test_load_appends_and_is_idempotent(self, tmp_path: Path) -> None:
        """A load appends with _loaded_at; the same upload is skipped."""
        warehouse = landing.LocalTableWarehouse(tmp_path, "t")
        item = SourceItem("f.xlsx", "f.xlsx", "v1", 1)

        assert warehouse.load("f.xlsx_abc", "abc", self.parquet(2), 2, item)
        assert not warehouse.load(
            "f.xlsx_abc", "abc", self.parquet(2), 2, item
        )

        table = pq.read_table(warehouse.table_path)
        assert table.num_rows == 2
        assert landing.LOADED_AT in table.column_names
        assert [row["source_file"] for row in warehouse.audit()] == ["f.xlsx"]

    def test_row_count_mismatch_is_a_service_error(
        self, tmp_path: Path
    ) -> None:
        """A wrong expected count fails the load (retried, not rejected)."""
        warehouse = landing.LocalTableWarehouse(tmp_path, "t")
        item = SourceItem("f.xlsx", "f.xlsx", "v1", 1)
        with pytest.raises(ServiceError, match="row count"):
            warehouse.load("k", "abc", self.parquet(2), 3, item)

    def test_reserved_column_is_rejected(self, tmp_path: Path) -> None:
        """Data with its own _loaded_at can't be loaded."""
        table = pa.table({landing.LOADED_AT: [1]})
        sink = pa.BufferOutputStream()
        pq.write_table(table, sink)
        warehouse = landing.LocalTableWarehouse(tmp_path, "t")
        item = SourceItem("f.xlsx", "f.xlsx", "v1", 1)
        with pytest.raises(ValidationError, match="_loaded_at"):
            warehouse.load("k", "abc", sink.getvalue().to_pybytes(), 1, item)

    def test_identity_is_a_plain_name(self, tmp_path: Path) -> None:
        """py-common puts the identity in keys: no colon or slash."""
        identity = landing.LocalTableWarehouse(tmp_path, "t").identity
        assert ":" not in identity and "/" not in identity


class TestLongPath:
    """Kept copies get a path Windows' 260-character limit can't stop."""

    def test_windows_gets_the_extended_form(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """On Windows the path gets the extended prefix; elsewhere not."""
        monkeypatch.setattr("hww_dashboard.landing.os.name", "posix")
        assert landing.long_path(tmp_path) == tmp_path
        monkeypatch.setattr("hww_dashboard.landing.os.name", "nt")
        assert str(landing.long_path(tmp_path)).startswith("\\\\?\\")


class TestLandedInputs:
    """Reading the newest load back, shaped like the workbook."""

    def test_newest_load_wins(
        self, tmp_path: Path, data_folder: Path, run_time: datetime
    ) -> None:
        """After a second upload, the reader returns only its rows."""
        config = landing_config(tmp_path, data_folder, read=True)
        landing.ingest(config, stage_from=data_folder / "inputs")
        book = tmp_path / "landing" / "peer" / "dummy_peer_montoring.xlsx"
        workbook = load_workbook(book)
        sheet = workbook.active
        assert sheet is not None
        sheet.delete_rows(3, sheet.max_row)
        workbook.save(book)
        landing.ingest(config)

        cfg = settings_of(config)
        inputs = landed.landed_inputs(
            cfg, tmp_path, Path(cfg["paths"]["mappings_folder"])
        )
        sheet_input = inputs.read("peer", cfg["peer"], "Peer mentoring", [])

        assert len(sheet_input.frame) == 1
        assert sheet_input.facts["table"] == "hww_peer"
        assert sheet_input.name == "dummy_peer_montoring.xlsx"

    def test_frame_matches_the_workbook_reader(
        self, landed_run: Path, data_folder: Path
    ) -> None:
        """Headings, row numbers and values match read_sheet's."""
        cfg = settings_of(landed_run / "config.toml")
        inputs = landed.landed_inputs(
            cfg, landed_run, Path(cfg["paths"]["mappings_folder"])
        )
        from_table = inputs.read("was", cfg["was"], "WAS database", []).frame
        from_book = wrangle.read_sheet(
            data_folder / "inputs" / WAS_FILE, 0, 1, "WAS database"
        )
        columns = [c for c in from_table.columns]
        assert list(from_table["excel_row"]) == list(from_book["excel_row"])
        left = from_table[columns].map(wrangle.clean_text)
        right = from_book[columns].map(wrangle.clean_text)
        pd.testing.assert_frame_equal(left, right)

    def test_missing_table_says_to_run_ingest(
        self, tmp_path: Path, data_folder: Path
    ) -> None:
        """Reading before ingest.py has run stops with a clear message."""
        config = landing_config(tmp_path, data_folder, read=True)
        with pytest.raises(wrangle.InputError, match="python ingest.py"):
            wrangle.run(config, output_folder=tmp_path / "out")


class TestBigQueryTables:
    """The BigQuery reader's queries, against a fake client."""

    def test_reads_the_newest_load_and_its_audit_row(self) -> None:
        """Rows come from the newest load; facts from the audit table."""
        loaded = datetime(2026, 10, 1, 9, 0)
        rows = pa.table(
            {
                "participant_id": [7],
                landing.ROW_FIELD: ["2"],
                landing.LOADED_AT: [loaded],
            }
        )
        queries: list[str] = []

        def query(sql: str, job_config: Any = None) -> SimpleNamespace:
            """Answer the audit query and the table read.

            Args:
                sql: The query text.
                job_config: Ignored.

            Returns:
                A result holding the audit row, or the table as Arrow.
            """
            queries.append(sql)
            if "FROM `p.d.audit`" in sql:
                key = "hww/was/dummy_was_database.xlsx_abcdef12"
                return SimpleNamespace(
                    result=lambda: [(key, "abcdef1234", loaded, 1)]
                )
            return SimpleNamespace(to_arrow=lambda: rows)

        tables = landed.BigQueryTables("p", "d", SimpleNamespace(query=query))
        load = tables.newest_load("hww_was")

        assert load.file == "dummy_was_database.xlsx"
        assert load.sha256 == "abcdef1234"
        assert landing.LOADED_AT not in load.rows.column_names
        assert "FROM `p.d.audit`" in queries[0]
        assert "destination = @destination" in queries[0]
        assert "WHERE _loaded_at = @loaded_at" in queries[1]


class TestCheckLanded:
    """[landed] settings are checked before anything runs."""

    @pytest.mark.parametrize(
        "section, message",
        [
            ({"read": "yes"}, "read must be true or false"),
            ({"target": "cloud"}, "target must be one of"),
            ({"target": "gcp"}, "project must be nonblank"),
            ({"tables_folder": ""}, "tables_folder must be nonblank"),
        ],
    )
    def test_bad_settings(self, section: dict[str, Any], message: str) -> None:
        """Each bad setting names itself."""
        with pytest.raises(wrangle.InputError, match=message):
            wrangle.check_landed(section, "config.toml")


class TestEndToEnd:
    """Workbooks -> py-common typed tables -> wrangle -> same tables."""

    def test_tables_match_the_golden_snapshot(
        self, landed_run: Path, tmp_path: Path, run_time: datetime
    ) -> None:
        """Every output CSV equals the one made from the workbooks."""
        out = tmp_path / "out"
        wrangle.run(
            landed_run / "config.toml", output_folder=out, now=run_time
        )

        for golden in sorted(GOLDEN.glob("*.csv")):
            expected = golden.read_bytes().replace(b"\r\n", b"\n")
            actual = (out / golden.name).read_bytes().replace(b"\r\n", b"\n")
            assert actual == expected, golden.name

    def test_run_record_names_the_landed_tables(
        self, landed_run: Path, tmp_path: Path, run_time: datetime
    ) -> None:
        """The run record says which table and load each input was."""
        out = tmp_path / "out"
        wrangle.run(
            landed_run / "config.toml", output_folder=out, now=run_time
        )

        record = json.loads((out / "run_record.json").read_text("utf-8"))
        tables = {
            entry["source"]: entry["table"] for entry in record["inputs"]
        }
        assert tables == {
            "Account signups": "hww_signups",
            "Survey export": "hww_survey",
            "WAS database": "hww_was",
            "Peer mentoring": "hww_peer",
        }


def test_stage_copies_each_named_workbook(
    tmp_path: Path, data_folder: Path
) -> None:
    """--stage puts each source's workbook in its landing subfolder."""
    config = landing_config(tmp_path, data_folder, read=False)
    copies = landing.stage(
        settings_of(config), data_folder / "inputs", tmp_path / "landing"
    )
    assert sorted(p.parent.name for p in copies) == sorted(wrangle.SOURCES)
    shutil.rmtree(tmp_path / "landing")


class TestLandingRegressions:
    """Failures found while reviewing the typed ingestion boundary."""

    def test_signups_rejects_unexpected_personal_column(
        self, tmp_path: Path, data_folder: Path
    ) -> None:
        """An extra signup column never reaches its typed table."""
        config = landing_config(tmp_path, data_folder, read=True)
        cfg = settings_of(config)
        landing.stage(cfg, data_folder / "inputs", tmp_path / "landing")
        book = tmp_path / "landing" / "signups" / cfg["signups"]["file"]
        workbook = load_workbook(book)
        sheet = workbook["Account signups"]
        column = sheet.max_column + 1
        sheet.cell(2, column, "Home address")
        sheet.cell(3, column, "Synthetic address")
        workbook.save(book)
        workbook.close()

        (result,) = landing.ingest(config)["signups"]

        assert result.outcome == Outcome.QUARANTINED
        assert "Home address" in "; ".join(result.errors)
        assert not (tmp_path / "landed" / "hww_signups.parquet").exists()

    def test_signups_requires_the_mixed_type_column(
        self, tmp_path: Path, data_folder: Path
    ) -> None:
        """Number of sites is required even without a cell type check."""
        config = landing_config(tmp_path, data_folder, read=True)
        cfg = settings_of(config)
        landing.stage(cfg, data_folder / "inputs", tmp_path / "landing")
        book = tmp_path / "landing" / "signups" / cfg["signups"]["file"]
        workbook = load_workbook(book)
        sheet = workbook["Account signups"]
        for cell in sheet[2]:
            if cell.value == "Number of sites":
                sheet.delete_cols(cell.column)
                break
        workbook.save(book)
        workbook.close()

        (result,) = landing.ingest(config)["signups"]

        assert result.outcome == Outcome.QUARANTINED
        assert "Number of sites" in "; ".join(result.errors)

    @pytest.mark.parametrize("source", wrangle.SOURCES)
    def test_allow_empty_is_per_source(
        self, source: str, fixture_config: Path, project_folder: Path
    ) -> None:
        """Allowing one empty source does not mutate other contracts."""
        cfg = deepcopy(settings_of(fixture_config))
        cfg[source]["allow_empty"] = True

        contracts = landing.source_contracts(cfg, project_folder / "mappings")

        assert contracts[source].worksheet.allow_empty
        defaults = landing.source_contracts(
            settings_of(fixture_config), project_folder / "mappings"
        )
        assert not defaults[source].worksheet.allow_empty

    def test_pattern_selects_newest_export_before_loading(
        self, tmp_path: Path, data_folder: Path
    ) -> None:
        """Filename dates win over discovery order and unrelated files."""
        config = landing_config(tmp_path, data_folder, read=True)
        cfg = settings_of(config)
        survey_file = cfg["survey"]["file"]
        pattern = "*healthy-working-wales-employer-survey-tool-*.xlsx"
        text = config.read_text(encoding="utf-8")
        config.write_text(
            text.replace(
                f'file = "{survey_file}"', f'file_pattern = "{pattern}"'
            ),
            encoding="utf-8",
        )
        cfg = settings_of(config)
        landing.stage(cfg, data_folder / "inputs", tmp_path / "landing")
        folder = tmp_path / "landing" / "survey"
        newest = "a-healthy-working-wales-employer-survey-tool-2026-10-01.xlsx"
        older = "z-healthy-working-wales-employer-survey-tool-2026-09-01.xlsx"
        for name in (newest, older, "unrelated-2026-12-01.xlsx"):
            shutil.copyfile(
                data_folder / "inputs" / survey_file, folder / name
            )

        results = landing.ingest(config)["survey"]

        assert [result.item.name for result in results] == [newest]
        assert results[0].outcome == Outcome.LOADED
        assert (
            landed.LocalTables(tmp_path / "landed")
            .newest_load("hww_survey")
            .file
            == newest
        )

    def test_audit_failure_cannot_publish_an_unreadable_load(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failed metadata write preserves a readable committed load."""
        warehouse = landing.LocalTableWarehouse(tmp_path, "t")
        data = TestLocalTableWarehouse.parquet(2)
        old = SourceItem("f.xlsx", "f.xlsx", "v1", 1)
        new = SourceItem("f.xlsx", "f.xlsx", "v2", 1)
        warehouse.load("old", "old", data, 2, old)
        original_open = Path.open

        def fail_audit(path: Path, *args: Any, **kwargs: Any) -> Any:
            """Refuse a separate append to the legacy audit file."""
            if path == warehouse.audit_path and args and args[0] == "a":
                raise OSError("simulated audit append failure")
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", fail_audit)
        try:
            written = warehouse.load("new", "new", data, 2, new)
        except ServiceError:
            written = False

        load = landed.LocalTables(tmp_path).newest_load("t")

        assert load.sha256 == ("new" if written else "old")
        assert load.rows.num_rows == 2

    def test_empty_load_replaces_previous_rows(self, tmp_path: Path) -> None:
        """An audited zero-row snapshot does not revive an older load."""
        warehouse = landing.LocalTableWarehouse(tmp_path, "t")
        warehouse.load(
            "old",
            "old",
            TestLocalTableWarehouse.parquet(2),
            2,
            SourceItem("f.xlsx", "f.xlsx", "v1", 1),
        )
        warehouse.load(
            "empty",
            "empty",
            TestLocalTableWarehouse.parquet(0),
            0,
            SourceItem("f.xlsx", "f.xlsx", "v2", 1),
        )

        load = landed.LocalTables(tmp_path).newest_load("t")

        assert load.rows.num_rows == 0
        assert load.sha256 == "empty"

    def test_failed_commit_preserves_previous_data_and_audit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failed final replacement is safe to retry exactly once."""
        warehouse = landing.LocalTableWarehouse(tmp_path, "t")
        data = TestLocalTableWarehouse.parquet(2)
        old = SourceItem("f.xlsx", "f.xlsx", "v1", 1)
        new = SourceItem("f.xlsx", "f.xlsx", "v2", 1)
        warehouse.load("old", "old", data, 2, old)
        before = warehouse.table_path.read_bytes()

        def refuse_replace(source: Any, destination: Any) -> None:
            """Simulate failure at the atomic publication boundary."""
            raise OSError("simulated replacement failure")

        with monkeypatch.context() as context:
            context.setattr("hww_dashboard.landing.os.replace", refuse_replace)
            with pytest.raises(ServiceError, match="replacement failure"):
                warehouse.load("new", "new", data, 2, new)

        assert warehouse.table_path.read_bytes() == before
        assert landed.LocalTables(tmp_path).newest_load("t").sha256 == "old"
        assert warehouse.load("new", "new", data, 2, new)
        assert not warehouse.load("new", "new", data, 2, new)
        assert pq.read_table(warehouse.table_path).num_rows == 4

    def test_legacy_tables_migrate_without_losing_history(
        self, tmp_path: Path
    ) -> None:
        """Existing separate Parquet and audit files remain readable."""
        warehouse = landing.LocalTableWarehouse(tmp_path, "t")
        loaded = datetime(2026, 10, 1, tzinfo=UTC)
        table = pa.table(
            {
                "name": ["Old employer"],
                landing.LOADED_AT: pa.array(
                    [loaded], type=pa.timestamp("us", tz="UTC")
                ),
            }
        )
        pq.write_table(table, warehouse.table_path)
        record = {
            "filename": "old",
            "checksum": "old",
            "destination": "t",
            "source_version": "v1",
            "source_file": "f.xlsx",
            "row_count": 1,
            "outcome": "LOADED",
            "timestamp": loaded.isoformat(),
        }
        warehouse.audit_path.write_text(json.dumps(record) + "\n")
        assert landed.LocalTables(tmp_path).newest_load("t").sha256 == "old"

        warehouse.load(
            "new",
            "new",
            TestLocalTableWarehouse.parquet(2),
            2,
            SourceItem("f.xlsx", "f.xlsx", "v2", 1),
        )

        assert len(warehouse.audit()) == 2
        assert landed.LocalTables(tmp_path).newest_load("t").sha256 == "new"

    def test_existing_survey_history_uses_filename_dates(
        self, tmp_path: Path
    ) -> None:
        """Older exports loaded last cannot win through legacy history."""
        warehouse = landing.LocalTableWarehouse(tmp_path, "t")
        data = TestLocalTableWarehouse.parquet(1)
        newest = "a-survey-2026-10-01.xlsx"
        older = "z-survey-2026-09-01.xlsx"
        for name in (newest, older):
            warehouse.load(
                name, name, data, 1, SourceItem(name, name, "v1", 1)
            )

        load = landed.LocalTables(tmp_path).newest_load(
            "t", {"file_pattern": "*-survey-*.xlsx"}
        )

        assert load.file == newest

    def test_exact_filename_can_select_a_previous_committed_load(
        self, tmp_path: Path
    ) -> None:
        """Changing a pinned file does not silently read another file."""
        warehouse = landing.LocalTableWarehouse(tmp_path, "t")
        data = TestLocalTableWarehouse.parquet(1)
        for name in ("wanted.xlsx", "other.xlsx"):
            warehouse.load(
                name, name, data, 1, SourceItem(name, name, "v1", 1)
            )

        load = landed.LocalTables(tmp_path).newest_load(
            "t", {"file": "wanted.xlsx"}
        )

        assert load.file == "wanted.xlsx"

    def test_bigquery_reads_empty_load_from_audit(self) -> None:
        """The newest committed audit row selects even an empty load."""
        loaded = datetime(2026, 10, 2, 9, 0)
        rows = pa.table(
            {
                "participant_id": pa.array([], type=pa.int64()),
                landing.ROW_FIELD: pa.array([], type=pa.string()),
                landing.LOADED_AT: pa.array([], type=pa.timestamp("us")),
            }
        )
        queries: list[str] = []

        def query(sql: str, job_config: Any = None) -> SimpleNamespace:
            """Return a committed empty load and its typed schema."""
            queries.append(sql)
            if "FROM `p.d.audit`" in sql:
                return SimpleNamespace(
                    result=lambda: [
                        ("hww/was/f.xlsx_abcdef12", "abcdef1234", loaded, 0)
                    ]
                )
            assert "MAX(_loaded_at)" not in sql
            return SimpleNamespace(to_arrow=lambda: rows)

        tables = landed.BigQueryTables("p", "d", SimpleNamespace(query=query))

        load = tables.newest_load("hww_was")

        assert load.rows.num_rows == 0
        assert load.loaded_at == loaded
        assert load.sha256 == "abcdef1234"
        assert "FROM `p.d.audit`" in queries[0]

    def test_empty_peer_snapshot_reaches_dashboard_tables(
        self, tmp_path: Path, data_folder: Path, run_time: datetime
    ) -> None:
        """The configured empty-source path works end to end."""
        config = landing_config(tmp_path, data_folder, read=True)
        config.write_text(
            config.read_text(encoding="utf-8").replace(
                "[peer]", "[peer]\nallow_empty = true"
            ),
            encoding="utf-8",
        )
        cfg = settings_of(config)
        landing.ingest(config, stage_from=data_folder / "inputs")
        book = tmp_path / "landing" / "peer" / cfg["peer"]["file"]
        workbook = load_workbook(book)
        sheet = workbook["query (1)"]
        sheet.delete_rows(2, sheet.max_row)
        workbook.save(book)
        workbook.close()

        (result,) = landing.ingest(config)["peer"]

        assert result.outcome == Outcome.LOADED
        assert result.rows_processed == 0
        tables = wrangle.run(
            config, output_folder=tmp_path / "out", now=run_time
        )
        assert "peer_mentoring_interest" not in set(
            tables["fact_engagement"]["event_type"]
        )


class TestSourceSelection:
    """Local and cloud discovery use the same export ordering rules."""

    def test_same_date_uses_modification_time_and_ignores_lock_files(
        self,
    ) -> None:
        """Lock files and unrelated names cannot outrank valid exports."""
        names = [
            "a-survey-2026-10-01.xlsx",
            "z-survey-2026-10-01.xlsx",
            "~$survey-2026-12-01.xlsx",
            "unrelated-2026-12-01.xlsx",
        ]
        items = [SourceItem(name, name, "1", 1) for name in names]
        source = SimpleNamespace(
            items=lambda: reversed(items), download=lambda item: b"original"
        )
        times = {names[0]: 2.0, names[1]: 1.0}
        selected = landing.NewestSource(
            source, "*survey-*.xlsx", lambda item: times[item.name]
        )

        (item,) = selected.items()

        assert item.name == names[0]
        assert selected.download(item) == b"original"

    def test_no_matches_produces_no_source_items(self) -> None:
        """A nonmatching file never reaches contract validation."""
        source = SimpleNamespace(
            items=lambda: [SourceItem("other.xlsx", "other.xlsx", "1", 1)]
        )
        selected = landing.NewestSource(source, "survey-*.xlsx", lambda _: 0)

        assert list(selected.items()) == []

    def test_cloud_build_selects_the_newest_matching_generation(
        self,
        fixture_config: Path,
        project_folder: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Cloud selection reads timestamps for discovered generations."""
        cfg = settings_of(fixture_config)
        cfg["survey"].pop("file")
        cfg["survey"]["file_pattern"] = "*survey-*.xlsx"
        names = ["a-survey-2026-10-01.xlsx", "z-survey-2026-09-01.xlsx"]
        items = [
            SourceItem(name, f"hww/survey/{name}", str(n), 1)
            for n, name in enumerate(names, 1)
        ]
        requested: list[tuple[str, int]] = []

        def get_blob(name: str, generation: int) -> SimpleNamespace:
            """Return metadata without contacting a cloud service."""
            requested.append((name, generation))
            return SimpleNamespace(updated=datetime(2026, 10, 2, tzinfo=UTC))

        source = SimpleNamespace(
            items=lambda: items,
            download=lambda item: b"generation bytes",
            bucket=SimpleNamespace(get_blob=get_blob),
        )
        monkeypatch.setattr(
            "py_common.adapters.gcs.GCSSource", lambda *args: source
        )
        monkeypatch.setattr(
            "py_common.adapters.gcs.GCSObjectStore",
            lambda *args: SimpleNamespace(),
        )
        monkeypatch.setattr(
            "py_common.adapters.bigquery.BigQueryWarehouse",
            lambda *args: SimpleNamespace(key_columns=[]),
        )
        settings = landing.LandingSettings(
            "gcp",
            tmp_path,
            tmp_path,
            tmp_path,
            project="p",
            dataset="d",
            landing_prefix="hww",
            landing_bucket="landing",
            store_bucket="store",
        )

        pipelines = landing.build_pipelines(
            cfg, project_folder / "mappings", settings
        )
        (selected,) = pipelines["survey"].source.items()

        assert selected == items[0]
        assert requested == [
            (item.identity, int(item.version)) for item in items
        ]
        assert (
            pipelines["survey"].source.download(selected)
            == b"generation bytes"
        )

    def test_missing_cloud_metadata_fails_closed(self) -> None:
        """A missing generation is not assigned a fabricated timestamp."""
        source = SimpleNamespace(
            bucket=SimpleNamespace(get_blob=lambda *args, **kwargs: None)
        )

        with pytest.raises(ServiceError, match="modification time"):
            landing.gcs_modified(
                source, SourceItem("f.xlsx", "hww/f.xlsx", "1", 1)
            )


class TestCommittedSnapshots:
    """Readers reject incomplete loads and preserve empty snapshots."""

    def test_first_local_load_can_be_empty(self, tmp_path: Path) -> None:
        """Audit metadata identifies a load with no data timestamps."""
        warehouse = landing.LocalTableWarehouse(tmp_path, "t")
        item = SourceItem("f.xlsx", "f.xlsx", "v1", 1)
        warehouse.load(
            "empty", "empty", TestLocalTableWarehouse.parquet(0), 0, item
        )

        load = landed.LocalTables(tmp_path).newest_load("t")

        assert load.rows.num_rows == 0
        assert load.file == "f.xlsx"
        assert load.sha256 == "empty"
        assert not warehouse.load(
            "empty", "empty", TestLocalTableWarehouse.parquet(0), 0, item
        )

    def test_missing_committed_cloud_load_does_not_query_data(self) -> None:
        """Rows without a successful audit cannot become current data."""

        def query(sql: str, job_config: Any = None) -> SimpleNamespace:
            """Return no committed loads and refuse any table query."""
            assert "FROM `p.d.audit`" in sql
            return SimpleNamespace(result=lambda: [])

        tables = landed.BigQueryTables("p", "d", SimpleNamespace(query=query))

        with pytest.raises(wrangle.InputError, match="no committed load"):
            tables.newest_load("hww_was")

    def test_cloud_history_selects_filename_date_before_load_time(
        self,
    ) -> None:
        """Historical uploads use the same filename policy as discovery."""
        newer = datetime(2026, 10, 2, tzinfo=UTC)
        older = datetime(2026, 10, 3, tzinfo=UTC)
        rows = pa.table({landing.LOADED_AT: [newer], "value": [1]})
        records = [
            ("z-survey-2026-09-01.xlsx_bbbbbbbb", "bbbbbbbb", older, 1),
            ("a-survey-2026-10-01.xlsx_aaaaaaaa", "aaaaaaaa", newer, 1),
        ]

        def query(sql: str, job_config: Any = None) -> SimpleNamespace:
            """Return audit history and verify the chosen timestamp."""
            if "FROM `p.d.audit`" in sql:
                assert "LIMIT 1" not in sql
                assert job_config.query_parameters[0].value == "p.d.t"
                return SimpleNamespace(result=lambda: records)
            assert job_config.query_parameters[0].value == newer
            return SimpleNamespace(to_arrow=lambda: rows)

        tables = landed.BigQueryTables("p", "d", SimpleNamespace(query=query))

        load = tables.newest_load("t", {"file_pattern": "*survey-*.xlsx"})

        assert load.file == "a-survey-2026-10-01.xlsx"
        assert load.sha256 == "aaaaaaaa"

    def test_cloud_row_count_must_match_committed_audit(self) -> None:
        """A partial or inconsistent snapshot cannot enter wrangling."""
        loaded = datetime(2026, 10, 2, tzinfo=UTC)
        rows = pa.table({landing.LOADED_AT: [loaded], "value": [1]})

        def query(sql: str, job_config: Any = None) -> SimpleNamespace:
            """Return a row count that disagrees with the actual data."""
            if "FROM `p.d.audit`" in sql:
                return SimpleNamespace(
                    result=lambda: [("f.xlsx_aaaaaaaa", "aaaaaaaa", loaded, 2)]
                )
            return SimpleNamespace(to_arrow=lambda: rows)

        tables = landed.BigQueryTables("p", "d", SimpleNamespace(query=query))

        with pytest.raises(wrangle.InputError, match="row count differs"):
            tables.newest_load("t")
