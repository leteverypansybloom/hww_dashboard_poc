"""The peer mentoring list as a Graph list export.

Each test writes the dummy workbook's rows as list items in a temporary
folder. Field names here are placeholders, as this list's mapping isn't
what is under test: tests/test_was_jsonl.py covers the export's form.
"""

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from openpyxl import load_workbook
from py_common import Outcome

from hww_dashboard import landing, wrangle
from hww_dashboard.wrangle import ITEM_ID, blank_id_text

GOLDEN = Path(__file__).resolve().parent / "golden"
WORKBOOK = "dummy_peer_montoring.xlsx"
EXPORT = "dummy_peer_montoring.jsonl"
SITE_ZONE = ZoneInfo("Europe/London")
BLANK_ID = "PM-item3"


def graph_value(value: Any) -> Any:
    """A cell's value as Graph sends it.

    Args:
        value: The workbook cell.

    Returns:
        A date as UTC text at local midnight, anything else unchanged.
    """
    if not isinstance(value, datetime):
        return value
    moment = value.replace(tzinfo=SITE_ZONE).astimezone(UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def list_items(data_folder: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """The workbook's rows as list items.

    Args:
        data_folder: tests/data.

    Returns:
        The items, with a blank value left out, and the headings. A
        heading's field name is Field and its position.
    """
    book = load_workbook(data_folder / "inputs" / WORKBOOK)
    rows = book.worksheets[0].iter_rows(values_only=True)
    headings = [str(heading) for heading in next(rows)]
    items = []
    for number, values in enumerate(rows, start=1):
        fields = {
            f"Field{index}": graph_value(value)
            for index, value in enumerate(values)
            if value is not None
        }
        items.append({"id": str(number), "fields": fields})
    book.close()
    return items, headings


def land(
    folder: Path,
    data_folder: Path,
    items: list[dict[str, Any]],
    headings: list[str],
) -> tuple[Path, Any]:
    """Land the items as the peer source, with the other workbooks.

    Args:
        folder: Folder for the inputs, config, store and tables.
        data_folder: tests/data.
        items: The list items.
        headings: The workbook's headings, by field position.

    Returns:
        The config file, and the peer file's result.
    """
    inputs = folder / "inputs"
    inputs.mkdir()
    for book in (data_folder / "inputs").glob("*.xlsx"):
        shutil.copy2(book, inputs)
    (inputs / EXPORT).write_text(
        "".join(f"{json.dumps(item)}\n" for item in items), encoding="utf-8"
    )
    loaded = {column.name for column in landing.PEER.columns}
    field_map = {
        heading: f"Field{index}"
        for index, heading in enumerate(headings)
        if heading in loaded
    }
    excluded = [
        f"Field{index}"
        for index, heading in enumerate(headings)
        if heading not in loaded
    ]
    project = data_folder.parent.parent
    text = (data_folder / "config.toml").read_text(encoding="utf-8")
    text = text.replace(
        'input_folder = "inputs"', f'input_folder = "{inputs.as_posix()}"'
    )
    text = text.replace(
        'mappings_folder = "../../mappings"',
        f'mappings_folder = "{(project / "mappings").as_posix()}"',
    )
    settings = [
        f'file = "{EXPORT}"',
        'site_time_zone = "Europe/London"',
        f"excluded_fields = {json.dumps(excluded)}",
    ]
    text = text.replace(f'file = "{WORKBOOK}"', "\n".join(settings))
    text += "\n[peer.field_map]\n" + "".join(
        f"{json.dumps(heading)} = {json.dumps(internal)}\n"
        for heading, internal in field_map.items()
    )
    text += '\n[landed]\nread = true\ntarget = "local"\n'
    config = folder / "config.toml"
    config.write_text(text, encoding="utf-8")
    (result,) = landing.ingest(config, stage_from=inputs)["peer"]
    return config, result


def peer_ids(config: Path, folder: Path, run_time: datetime) -> list[str]:
    """Build the tables and read the peer ids from them.

    Args:
        config: The config file.
        folder: The run's folder.
        run_time: Fixed analysis timestamp.

    Returns:
        Each peer id in fact_engagement.csv.
    """
    wrangle.run(config, output_folder=folder / "out", now=run_time)
    lines = (folder / "out" / "fact_engagement.csv").read_text(
        encoding="utf-8"
    )
    return [
        line.rsplit(",", 1)[1]
        for line in lines.splitlines()
        if line.startswith("peer_mentoring_interest-")
    ]


def test_blank_id_text_prefers_the_item_id() -> None:
    """The row number is only for a file with no item IDs."""
    assert blank_id_text("3", 4) == "item3"
    assert blank_id_text(None, 4) == "row4"
    assert blank_id_text(float("nan"), 4) == "row4"


class TestPeerExport:
    """A peer export gives the workbook's tables and stable ids."""

    def test_tables_match_the_golden_files(
        self, tmp_path: Path, data_folder: Path, run_time: datetime
    ) -> None:
        """With every Participant ID present, nothing differs.

        Args:
            tmp_path: Isolated test folder.
            data_folder: tests/data.
            run_time: Fixed analysis timestamp.
        """
        items, headings = list_items(data_folder)
        config, result = land(tmp_path, data_folder, items, headings)
        assert result.outcome == Outcome.LOADED
        wrangle.run(config, output_folder=tmp_path / "out", now=run_time)
        for golden in GOLDEN.glob("*.csv"):
            written = tmp_path / "out" / golden.name
            assert written.read_text(encoding="utf-8") == golden.read_text(
                encoding="utf-8"
            ), golden.name

    def test_each_row_has_its_item_id(
        self, tmp_path: Path, data_folder: Path
    ) -> None:
        """The envelope's id loads beside the mapped columns.

        Args:
            tmp_path: Isolated test folder.
            data_folder: tests/data.
        """
        items, headings = list_items(data_folder)
        land(tmp_path, data_folder, items, headings)
        tables = tmp_path / "landed"
        record = landing.local_audit(tables, "hww_peer")[-1]
        rows = landing.local_rows(tables, "hww_peer", record)
        assert [row["payload"][ITEM_ID] for row in rows] == [
            item["id"] for item in items
        ]

    @pytest.mark.parametrize("deleted", [0, 1], ids=["all", "first deleted"])
    def test_blank_participant_id_uses_the_item_id(
        self,
        tmp_path: Path,
        data_folder: Path,
        run_time: datetime,
        deleted: int,
    ) -> None:
        """The id holds when deleting an earlier item moves its line.

        Args:
            tmp_path: Isolated test folder.
            data_folder: tests/data.
            run_time: Fixed analysis timestamp.
            deleted: How many items to delete from the start.
        """
        items, headings = list_items(data_folder)
        del items[2]["fields"]["Field0"]
        config, result = land(tmp_path, data_folder, items[deleted:], headings)
        assert result.outcome == Outcome.LOADED
        ids = peer_ids(config, tmp_path, run_time)
        assert BLANK_ID in ids
        assert "PM-0003" not in ids
        assert "PM-0002" in ids

    def test_missing_item_id_quarantines(
        self, tmp_path: Path, data_folder: Path
    ) -> None:
        """An item with no id can't be identified, so the file stops.

        Args:
            tmp_path: Isolated test folder.
            data_folder: tests/data.
        """
        items, headings = list_items(data_folder)
        del items[0]["id"]
        _, result = land(tmp_path, data_folder, items, headings)
        assert result.outcome == Outcome.QUARANTINED
        assert "needs a Graph item id" in "; ".join(result.errors)
