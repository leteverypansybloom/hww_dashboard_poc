"""The WAS database as a Graph list export, from landing to the tables.

tests/data/inputs/dummy_was_database.jsonl holds the same rows as the
dummy workbook in the form the SharePoint transfer delivers, and
tests/data/was_graph.toml says how its fields map to the WAS contract.
Apart from the id of a request with no Participant ID, it must build
the same tables as the workbook.
"""

import importlib.util
import json
import re
import shutil
import tomllib
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pandas as pd
import pytest
from py_common import Outcome

from hww_dashboard import landing, wrangle
from hww_dashboard.wrangle import WAS_ITEM_ID

PROJECT = Path(__file__).resolve().parent.parent
SCRIPT = PROJECT / "scripts" / "make_was_jsonl.py"
GOLDEN = PROJECT / "tests" / "golden"
WORKBOOK = "dummy_was_database.xlsx"
EXPORT = "dummy_was_database.jsonl"
ROWS = 35
ENQUIRY = "Date_x0020_of_x0020_Enquiry"
BLANK_ID_LINE = 21
BLANK_ID = f"WAS-item{BLANK_ID_LINE}"


def land_config(folder: Path, data_folder: Path, export: bool) -> Path:
    """Write a config that lands the WAS source and reads it back.

    Args:
        folder: Folder for the config, landing folder, store and tables.
        data_folder: tests/data.
        export: Read WAS from the export rather than the workbook.

    Returns:
        The config file.
    """
    project = data_folder.parent.parent
    text = (data_folder / "config.toml").read_text(encoding="utf-8")
    text = text.replace(
        'input_folder = "inputs"',
        f'input_folder = "{(data_folder / "inputs").as_posix()}"',
    )
    text = text.replace(
        'mappings_folder = "../../mappings"',
        f'mappings_folder = "{(project / "mappings").as_posix()}"',
    )
    if export:
        graph = tomllib.loads(
            (data_folder / "was_graph.toml").read_text(encoding="utf-8")
        )
        settings = [
            f'file = "{EXPORT}"',
            f'site_time_zone = "{graph["site_time_zone"]}"',
            f"excluded_fields = {json.dumps(graph['excluded_fields'])}",
        ]
        text = text.replace(f'file = "{WORKBOOK}"', "\n".join(settings))
        text += "\n[was.field_map]\n" + "".join(
            f"{json.dumps(heading)} = {json.dumps(internal)}\n"
            for heading, internal in graph["field_map"].items()
        )
    text += '\n[landed]\nread = true\ntarget = "local"\n'
    path = folder / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def was_payloads(folder: Path) -> dict[int, dict[str, Any]]:
    """The newest WAS load in a run's local tables.

    Args:
        folder: The run's folder.

    Returns:
        Row number -> payload.
    """
    tables = folder / "landed"
    record = landing.local_audit(tables, "hww_was")[-1]
    rows = landing.local_rows(tables, "hww_was", record)
    return {row["row_number"]: row["payload"] for row in rows}


def items(data_folder: Path) -> list[dict[str, Any]]:
    """The export's list items.

    Args:
        data_folder: tests/data.

    Returns:
        One parsed object per line.
    """
    text = (data_folder / "inputs" / EXPORT).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


@pytest.fixture(scope="module")
def export_run(
    tmp_path_factory: pytest.TempPathFactory, data_folder: Path
) -> Path:
    """Land the export once.

    Args:
        tmp_path_factory: For a folder shared by this module.
        data_folder: tests/data.

    Returns:
        The folder holding config.toml, landing/, store/ and landed/.
    """
    folder = tmp_path_factory.mktemp("export")
    config = land_config(folder, data_folder, export=True)
    text, ok = landing.summary(
        landing.ingest(config, stage_from=data_folder / "inputs")
    )
    assert ok, text
    return folder


@pytest.fixture(scope="module")
def workbook_run(
    tmp_path_factory: pytest.TempPathFactory, data_folder: Path
) -> Path:
    """Land the workbook once, for comparison.

    Args:
        tmp_path_factory: For a folder shared by this module.
        data_folder: tests/data.

    Returns:
        The folder holding config.toml, landing/, store/ and landed/.
    """
    folder = tmp_path_factory.mktemp("workbook")
    config = land_config(folder, data_folder, export=False)
    text, ok = landing.summary(
        landing.ingest(config, stage_from=data_folder / "inputs")
    )
    assert ok, text
    return folder


class TestExportFile:
    """The file has the form a Graph list export has."""

    def test_it_is_what_the_script_writes(self, data_folder: Path) -> None:
        """The committed file is the workbook, converted.

        Args:
            data_folder: tests/data.
        """
        spec = importlib.util.spec_from_file_location("make_was_jsonl", SCRIPT)
        assert spec is not None and spec.loader is not None
        script: ModuleType = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script)
        path = data_folder / "inputs" / EXPORT
        assert script.export_text() == path.read_bytes().decode("utf-8")

    def test_every_line_is_one_list_item(self, data_folder: Path) -> None:
        """Each object has Graph's envelope around nested fields.

        Args:
            data_folder: tests/data.
        """
        found = items(data_folder)
        assert len(found) == ROWS
        assert [item["id"] for item in found] == [
            str(number) for number in range(1, ROWS + 1)
        ]
        for item in found:
            assert {"createdDateTime", "lastModifiedDateTime"} < set(item)
            assert isinstance(item["fields"], dict)

    def test_field_names_are_not_the_headings(self, data_folder: Path) -> None:
        """Fields use internal names of at most 32 characters, plus a clash.

        Args:
            data_folder: tests/data.
        """
        fields = items(data_folder)[0]["fields"]
        assert "Date of Enquiry" not in fields
        assert ENQUIRY in fields
        columns = [
            name for name in fields if "_x00" in name and "@odata" not in name
        ]
        assert all(len(name) <= 33 for name in columns)

    def test_a_blank_value_is_left_out(self, data_folder: Path) -> None:
        """Graph doesn't send a field with no value.

        Args:
            data_folder: tests/data.
        """
        fields = items(data_folder)[BLANK_ID_LINE - 1]["fields"]
        assert "Participant_x0020_ID" not in fields
        assert ENQUIRY not in fields

    def test_a_summer_date_is_the_day_before_in_utc(
        self, data_folder: Path
    ) -> None:
        """Local midnight in UK summer time is 23:00 UTC the day before.

        Args:
            data_folder: tests/data.
        """
        fields = items(data_folder)[0]["fields"]
        assert fields["Date_x0020_Summary_x0020_2_x0020"] == (
            "2026-06-30T23:00:00Z"
        )

    def test_personal_values_are_reserved_examples(
        self, data_folder: Path
    ) -> None:
        """Every email and link is synthetic or Graph's own address.

        Args:
            data_folder: tests/data.
        """
        text = (data_folder / "inputs" / EXPORT).read_text(encoding="utf-8")
        emails = re.findall(r"[\w.+-]+@(?!odata\.)[\w-]+\.[\w.-]+", text)
        assert emails
        assert {email.split("@")[1] for email in emails} == {"example.org"}
        assert set(re.findall(r"https?://([^/\s\"]+)", text)) == {
            "example.org",
            "graph.microsoft.com",
        }


class TestLanding:
    """The export lands as the workbook lands."""

    def test_payloads_match_the_workbook(
        self, export_run: Path, workbook_run: Path
    ) -> None:
        """Every value is what the workbook route loads.

        A line number counts from 1 and a workbook's rows from 2, below
        the headings.

        Args:
            export_run: Folder of the export's run.
            workbook_run: Folder of the workbook's run.
        """
        from_export = was_payloads(export_run)
        from_book = was_payloads(workbook_run)
        assert len(from_export) == ROWS
        for payload in from_export.values():
            del payload[WAS_ITEM_ID]
        assert from_export == {
            row - 1: payload for row, payload in from_book.items()
        }

    def test_only_mapped_columns_are_loaded(
        self, export_run: Path, data_folder: Path
    ) -> None:
        """Contact details and SharePoint's fields stay out of the table.

        Args:
            export_run: Folder of the export's run.
            data_folder: tests/data.
        """
        graph = tomllib.loads(
            (data_folder / "was_graph.toml").read_text(encoding="utf-8")
        )
        for payload in was_payloads(export_run).values():
            assert set(payload) == {*graph["field_map"], WAS_ITEM_ID}
        rows = "".join(
            path.read_text(encoding="utf-8")
            for path in (export_run / "landed" / "hww_was").rglob("*")
            if path.is_file()
        )
        assert "example.org/" not in rows
        for value in ("@example.org", "Jan Job", "John Job", "webUrl"):
            assert value not in rows

    def test_each_row_has_its_item_id(self, export_run: Path) -> None:
        """The envelope's id loads as text beside the mapped columns.

        Args:
            export_run: Folder of the export's run.
        """
        for line, payload in was_payloads(export_run).items():
            assert payload[WAS_ITEM_ID] == str(line)

    def test_the_original_file_is_kept(
        self, export_run: Path, data_folder: Path
    ) -> None:
        """The raw copy has the original bytes, envelope included.

        Args:
            export_run: Folder of the export's run.
            data_folder: tests/data.
        """
        copies = [
            path
            for path in (export_run / "store" / "raw").rglob(EXPORT)
            if path.is_file()
        ]
        assert len(copies) == 1
        original = (data_folder / "inputs" / EXPORT).read_bytes()
        assert copies[0].read_bytes() == original

    def test_landing_it_again_loads_nothing(self, export_run: Path) -> None:
        """The same upload isn't loaded twice.

        Args:
            export_run: Folder of the export's run.
        """
        results = landing.ingest(export_run / "config.toml")
        (was,) = results["was"]
        assert was.outcome == Outcome.SKIPPED


class TestChangedExports:
    """What a real export might do differently."""

    def land(
        self,
        folder: Path,
        data_folder: Path,
        change: Callable[[dict[str, Any]], None],
        first_line: int = 1,
    ) -> tuple[Path, Any]:
        """Land the export with a change made to every item.

        Args:
            folder: Folder for the run.
            data_folder: tests/data.
            change: Changes one parsed item in place.
            first_line: The first line to keep, as if the items before
                it had been deleted from the list.

        Returns:
            The config file, and the WAS file's result.
        """
        config = land_config(folder, data_folder, export=True)
        landing.stage(
            wrangle.load_config(config),
            data_folder / "inputs",
            folder / "landing",
        )
        lines = []
        for item in items(data_folder)[first_line - 1 :]:
            change(item)
            lines.append(json.dumps(item, ensure_ascii=False))
        path = folder / "landing" / "was" / EXPORT
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        (result,) = landing.ingest(config)["was"]
        return config, result

    def test_new_list_column_quarantines_without_its_value(
        self, tmp_path: Path, data_folder: Path
    ) -> None:
        """A column nobody has decided about stops the file.

        Args:
            tmp_path: Isolated test folder.
            data_folder: tests/data.
        """

        def add(item: dict[str, Any]) -> None:
            """Add an unknown field.

            Args:
                item: The list item.
            """
            item["fields"]["Home_x0020_address"] = "1 High Street"

        _, result = self.land(tmp_path, data_folder, add)
        assert result.outcome == Outcome.QUARANTINED
        assert "1 unrecognised field" in "; ".join(result.errors)
        assert "High Street" not in "; ".join(result.errors)
        assert not (tmp_path / "landed" / "hww_was").exists()

    def test_missing_fields_object_quarantines(
        self, tmp_path: Path, data_folder: Path
    ) -> None:
        """An export without $expand=fields is refused.

        Args:
            tmp_path: Isolated test folder.
            data_folder: tests/data.
        """
        _, result = self.land(
            tmp_path, data_folder, lambda item: item.pop("fields")
        )
        assert result.outcome == Outcome.QUARANTINED
        assert "needs a fields object" in "; ".join(result.errors)

    def test_missing_item_id_quarantines(
        self, tmp_path: Path, data_folder: Path
    ) -> None:
        """An item with no id can't be identified, so the file stops.

        Args:
            tmp_path: Isolated test folder.
            data_folder: tests/data.
        """
        _, result = self.land(
            tmp_path, data_folder, lambda item: item.pop("id")
        )
        assert result.outcome == Outcome.QUARANTINED
        assert "needs a Graph item id" in "; ".join(result.errors)

    def test_deleting_earlier_items_keeps_the_id(
        self, tmp_path: Path, data_folder: Path, run_time: datetime
    ) -> None:
        """The request keeps its id when its line number changes.

        Args:
            tmp_path: Isolated test folder.
            data_folder: tests/data.
            run_time: Fixed analysis timestamp.
        """
        config, result = self.land(
            tmp_path, data_folder, lambda item: None, first_line=6
        )
        assert result.outcome == Outcome.LOADED
        wrangle.run(config, output_folder=tmp_path / "out", now=run_time)
        written = (tmp_path / "out" / "fact_was_session.csv").read_text(
            encoding="utf-8"
        )
        assert f"{BLANK_ID}-S1," in written

    @pytest.mark.parametrize("kind", [float, str])
    def test_participant_id_as_decimal_or_text_gives_the_same_ids(
        self,
        tmp_path: Path,
        data_folder: Path,
        run_time: datetime,
        kind: Callable[[int], Any],
    ) -> None:
        """A number column may send 1.0, and a text column "1".

        Args:
            tmp_path: Isolated test folder.
            data_folder: tests/data.
            run_time: Fixed analysis timestamp.
            kind: Turns the ID into the form under test.
        """

        def convert(item: dict[str, Any]) -> None:
            """Change the item's Participant ID.

            Args:
                item: The list item.
            """
            fields = item["fields"]
            if "Participant_x0020_ID" in fields:
                fields["Participant_x0020_ID"] = kind(
                    fields["Participant_x0020_ID"]
                )

        config, result = self.land(tmp_path, data_folder, convert)
        assert result.outcome == Outcome.LOADED
        wrangle.run(config, output_folder=tmp_path / "out", now=run_time)
        written = tmp_path / "out" / "fact_was_session.csv"
        golden = (GOLDEN / "fact_was_session.csv").read_text(encoding="utf-8")
        assert written.read_text(encoding="utf-8") == _with_item_id(golden)


def _with_item_id(text: str) -> str:
    """Golden text with the blank-ID request's id from the export.

    A request with no Participant ID takes its id from its row in a
    workbook, and from its SharePoint item in an export.

    Args:
        text: A golden file's text.

    Returns:
        The text the export should give.
    """
    return text.replace("WAS-row22", BLANK_ID)


@pytest.fixture(scope="module")
def tables(
    export_run: Path,
    tmp_path_factory: pytest.TempPathFactory,
    run_time: datetime,
) -> Path:
    """Build the tables once from the landed export.

    Args:
        export_run: Folder of the export's run.
        tmp_path_factory: For the copy the pipeline writes into.
        run_time: Fixed analysis timestamp.

    Returns:
        The output folder.
    """
    folder = tmp_path_factory.mktemp("tables")
    shutil.copytree(export_run, folder, dirs_exist_ok=True)
    wrangle.run(
        folder / "config.toml",
        output_folder=folder / "out",
        now=run_time,
    )
    return folder / "out"


def test_an_item_id_alone_is_a_blank_row() -> None:
    """A row holding only its item id is dropped like any blank row."""
    frame = pd.DataFrame(
        {
            "Title": [float("nan"), "Org 2"],
            WAS_ITEM_ID: ["1", "2"],
            "excel_row": [1, 2],
        }
    )
    assert list(wrangle.drop_blank_rows(frame)["excel_row"]) == [2]


class TestTables:
    """The tables built from the export match the workbook's."""

    @pytest.mark.parametrize(
        "name", sorted(path.name for path in GOLDEN.glob("*.csv"))
    )
    def test_table_matches_the_golden_file(
        self, tables: Path, name: str
    ) -> None:
        """Every table is the workbook's, apart from one request's id.

        Args:
            tables: The output folder.
            name: The table's file name.
        """
        golden = (GOLDEN / name).read_text(encoding="utf-8")
        written = (tables / name).read_text(encoding="utf-8")
        assert written == _with_item_id(golden)

    def test_report_names_the_export_and_the_line(self, tables: Path) -> None:
        """The data quality report points at where to look.

        Args:
            tables: The output folder.
        """
        report = (tables / "data_quality_report.md").read_text(
            encoding="utf-8"
        )
        assert f"35 rows read from {EXPORT}" in report
        assert (
            f"WAS row {BLANK_ID_LINE}: no Participant ID, using id "
            f"'item{BLANK_ID_LINE}'"
        ) in report

    def test_item_id_cannot_clash_with_a_participant_id(
        self, tables: Path
    ) -> None:
        """Participant ID 21 and SharePoint item 21 stay different requests.

        Args:
            tables: The output folder.
        """
        written = (tables / "fact_was_session.csv").read_text(encoding="utf-8")
        assert f"WAS-{BLANK_ID_LINE}-S1," in written
        assert f"{BLANK_ID}-S1," in written
