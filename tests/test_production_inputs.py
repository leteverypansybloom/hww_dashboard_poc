"""Production input configuration and publication boundaries."""

import json
import re
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from py_common import GraphJsonLinesContract

from hww_dashboard import landed, landing, publishing, service, wrangle


class TestWorkbooks:
    """Workbook and Graph routes share canonical reporting fields."""

    def test_graph_mapping_is_required(
        self, fixture_config: Path, project_folder: Path
    ) -> None:
        """Migrated list names alone cannot enable an unknown schema.

        Args:
            fixture_config: Frozen synthetic configuration.
            project_folder: Project source folder.
        """
        cfg = wrangle.load_config(fixture_config)
        cfg["was"]["file"] = "WAS database.jsonl"
        with pytest.raises(wrangle.InputError, match="configure Graph"):
            landing.workbooks(cfg, project_folder / "mappings")

    def test_graph_values_use_explicit_internal_mappings(
        self, fixture_config: Path, project_folder: Path
    ) -> None:
        """Synthetic internal names are mapped without changing source bytes.

        Args:
            fixture_config: Frozen synthetic configuration.
            project_folder: Project source folder.
        """
        cfg = wrangle.load_config(fixture_config)
        cfg["was"]["file"] = "WAS database.jsonl"
        columns = landing.WAS.columns
        mappings = {
            column.name: f"SyntheticField{index}"
            for index, column in enumerate(columns)
            if column.name != "Participant ID"
        }
        cfg["was"]["field_map"] = mappings
        cfg["was"]["metadata_map"] = {"Participant ID": "id"}
        cfg["was"]["site_time_zone"] = "Europe/London"
        contract = landing.workbooks(cfg, project_folder / "mappings")[
            "was"
        ].contract
        assert isinstance(contract, GraphJsonLinesContract)
        fields: dict[str, Any] = {
            internal: None for internal in mappings.values()
        }
        fields[mappings["Title"]] = "Synthetic organisation"
        data = json.dumps({"id": "42", "fields": fields}).encode()
        selected = contract.read(data, "WAS database.jsonl")["query"]
        assert selected.rows[0][1][0] == "42"
        assert "Synthetic organisation" in selected.rows[0][1]
        assert json.loads(data)["fields"] == fields


class TestWorkbooksGraphValues:
    """A real list's values reach the tables in the workbook's form."""

    @pytest.fixture
    def contract(
        self, fixture_config: Path, project_folder: Path
    ) -> GraphJsonLinesContract:
        """The WAS contract for a synthetic list export.

        Args:
            fixture_config: Frozen synthetic configuration.
            project_folder: Project source folder.

        Returns:
            The contract.
        """
        cfg = wrangle.load_config(fixture_config)
        cfg["was"]["file"] = "WAS database.jsonl"
        cfg["was"]["site_time_zone"] = "Europe/London"
        cfg["was"]["field_map"] = {
            column.name: f"Field{index}"
            for index, column in enumerate(landing.WAS.columns)
        }
        contract = landing.workbooks(cfg, project_folder / "mappings")[
            "was"
        ].contract
        assert isinstance(contract, GraphJsonLinesContract)
        return contract

    def row(
        self, contract: GraphJsonLinesContract, heading: str, value: Any
    ) -> Any:
        """Read one list item holding one value.

        Args:
            contract: The contract.
            heading: The canonical heading the value belongs to.
            value: The value as Graph sends it.

        Returns:
            The selected value.
        """
        fields = {contract.field_map[heading]: value}
        for name, internal in contract.field_map.items():
            if name != heading:
                fields[internal] = "x" if name == "Title" else None
        data = json.dumps({"id": "1", "fields": fields}).encode()
        sheet = contract.read(data, "WAS database.jsonl")["query"]
        return sheet.rows[0][1][sheet.columns.index(heading)]

    def test_multi_choice_topics_join_as_in_a_workbook(
        self, contract: GraphJsonLinesContract
    ) -> None:
        """Graph's list of topics becomes the separated workbook text.

        Args:
            contract: The contract.
        """
        heading = "Topics discussed in session 1"
        assert self.row(contract, heading, ["A", "B"]) == "A;#B"

    def test_summer_date_keeps_its_day(
        self, contract: GraphJsonLinesContract
    ) -> None:
        """A UK date in summer isn't read as the day before.

        Args:
            contract: The contract.
        """
        value = self.row(contract, "Date of Enquiry", "2026-05-31T23:00:00Z")
        assert value == "2026-06-01T00:00:00"


class TestIngest:
    """One folder's failure doesn't stop the others, or hide the error."""

    def test_unexpected_error_is_raised_after_every_folder(
        self, fixture_config: Path
    ) -> None:
        """main() can report the error as unexpected, with its traceback.

        Args:
            fixture_config: Frozen synthetic configuration.
        """
        broken = MagicMock()
        broken.run.side_effect = RuntimeError("synthetic")
        healthy = MagicMock()
        healthy.run.return_value = []
        pipelines = {"broken": broken, "healthy": healthy}
        with (
            patch.object(landing, "build_pipelines", return_value=pipelines),
            pytest.raises(RuntimeError, match="synthetic"),
        ):
            landing.ingest(fixture_config)
        healthy.run.assert_called_once()

    def test_unexpected_error_exits_two(self, fixture_config: Path) -> None:
        """A bug or a held lock isn't reported as a problem to fix by hand.

        Args:
            fixture_config: Frozen synthetic configuration.
        """
        broken = MagicMock()
        broken.run.side_effect = RuntimeError("synthetic")
        with patch.object(
            landing, "build_pipelines", return_value={"broken": broken}
        ):
            assert landing.main([str(fixture_config)]) == 2


class TestProductionConfig:
    """Python and Dataform agree on each production export name."""

    def test_names_match_dataform(self, project_folder: Path) -> None:
        """Both implementations select the owner's agreed filenames.

        Args:
            project_folder: Project source folder.
        """
        with (project_folder / "config.gcp.toml").open("rb") as stream:
            cfg = tomllib.load(stream)
        settings = (
            project_folder / "dataform/workflow_settings.yaml"
        ).read_text("utf-8")
        for source in ("signups", "survey", "was", "peer"):
            key = "signups_file" if source == "survey" else f"{source}_file"
            match = re.search(rf"^\s*{key}:\s*(.+)$", settings, re.M)
            assert match is not None
            assert match.group(1).strip("\"'") == cfg[source]["file"]


class TestSelectedAudit:
    """Delayed old generations cannot replace a newer snapshot."""

    def test_generation_precedes_commit_time(self) -> None:
        """GCS generation order wins when commit times arrive out of order."""
        records = [
            {
                "outcome": "LOADED",
                "source_file": "f.jsonl",
                "source_version": "100",
                "timestamp": "2026-11-04T12:00:00+00:00",
            },
            {
                "outcome": "LOADED",
                "source_file": "f.jsonl",
                "source_version": "200",
                "timestamp": "2026-11-04T11:00:00+00:00",
            },
        ]
        assert (
            landed.selected_audit(records, "t", None)["source_version"]
            == "200"
        )


class TestPublicationLock:
    """The reporting lease covers both reads and publication."""

    def test_gcp_work_is_inside_one_lease(
        self, fixture_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GCP publication acquires the shared lease before work starts.

        Args:
            fixture_config: Frozen synthetic configuration.
            monkeypatch: Replaces configuration loading.
        """
        cfg = wrangle.load_config(fixture_config)
        cfg["landed"] = {
            "target": "gcp",
            "project": "p",
            "dataset": "d",
            "store_bucket": "store",
        }
        monkeypatch.setattr(wrangle, "load_config", lambda path: cfg)
        events: list[str] = []
        store = MagicMock()
        store.lock.return_value.__enter__.side_effect = lambda: events.append(
            "enter"
        )
        store.lock.return_value.__exit__.side_effect = (
            lambda *args: events.append("exit")
        )
        with patch(
            "py_common.adapters.gcs.GCSObjectStore", return_value=store
        ):
            with publishing.publication_lock(fixture_config):
                events.append("read and publish")
        assert events == ["enter", "read and publish", "exit"]


class TestLandedInputsRead:
    """Source freshness is checked against the analysis timestamp."""

    def test_overdue_source_holds_publication(self) -> None:
        """A missing monthly upload cannot look like current reporting."""
        tables = MagicMock()
        tables.newest_load.return_value = landed.Load(
            [], "f.jsonl", "checksum", datetime(2026, 1, 1, tzinfo=UTC)
        )
        contract = landing.SourceContract(landing.WAS, "hww_was")
        inputs = landed.LandedInputs(
            tables, {"was": contract}, 24, datetime(2026, 1, 3, tzinfo=UTC)
        )
        with pytest.raises(wrangle.InputError, match="overdue"):
            inputs.read("was", {}, "WAS", [])


class TestOnUpload:
    """The Cloud Run wrapper releases its logging handlers."""

    def test_entry_point_closes_handlers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The entry point handles an event without calling cloud services.

        Args:
            monkeypatch: Replaces the service and logging boundaries.
        """
        calls: list[Any] = []
        monkeypatch.setattr(service, "configure_logging", lambda *args: [])
        monkeypatch.setattr(service, "close_logging", calls.append)
        monkeypatch.setattr(service, "handle", lambda data, config: "rebuilt")
        service.on_upload(SimpleNamespace(data={}))
        assert calls == [[]]
