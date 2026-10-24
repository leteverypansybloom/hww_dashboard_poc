"""Checks on the upload-triggered Cloud Run service (service.py).

py-common's handle_upload, which ingests the upload's folder, is
replaced by a stand-in returning chosen results, so these tests check
the service's own decisions: which pipelines run for an upload, when
to rebuild the tables, and which problems are retried.
"""

import base64
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("py_common")

from py_common.model import Outcome, Result, SourceItem  # noqa: E402

from hww_dashboard import landing, service, wrangle  # noqa: E402

#: Stand-ins for the pipelines, by landing folder, as the shipped config
#: has them: one per workbook.
PIPELINES: dict[str, Any] = {
    "hww/signups": "monitoring workbook pipeline",
    "hww/was": "was pipeline",
    "hww/peer": "peer pipeline",
}


def result(outcome: Outcome, errors: list[str] | None = None) -> Result:
    """A py-common Result for one file.

    Args:
        outcome: What happened to the file.
        errors: Its error messages.

    Returns:
        The result.
    """
    item = SourceItem("was.xlsx", "hww/was/was.xlsx", "1", 10)
    return Result(item, outcome, "abc", 1, errors or [], 0.1)


def event(name: str) -> dict[str, Any]:
    """The CloudEvent data Eventarc delivers for an upload.

    Args:
        name: The uploaded object's name, e.g. "hww/was/was.xlsx".

    Returns:
        A Pub/Sub push body holding the GCS notification.
    """
    notification = {"bucket": "landing", "name": name, "generation": "1"}
    return {
        "message": {
            "data": base64.b64encode(
                json.dumps(notification).encode("utf-8")
            ).decode("ascii"),
            "attributes": {"eventType": "OBJECT_FINALIZE"},
        }
    }


WAS_UPLOAD = event("hww/was/was.xlsx")


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record the pipelines each handle_upload call is given.

    Args:
        monkeypatch: Replaces folder_pipelines.

    Returns:
        A list that fills with each call's folder -> pipeline mapping.
    """
    monkeypatch.setattr(
        "hww_dashboard.service.folder_pipelines", lambda path: PIPELINES
    )
    return []


@pytest.fixture
def uploads(
    monkeypatch: pytest.MonkeyPatch, calls: list[dict[str, Any]]
) -> list[list[Result]]:
    """Replace handle_upload with one returning the next listed results.

    Args:
        monkeypatch: Replaces handle_upload.
        calls: Records what each call was given.

    Returns:
        A list the test fills with handle_upload's next return values.
    """
    queue: list[list[Result]] = []

    def fake_handle_upload(
        data: Any, pipelines: dict[str, Any]
    ) -> list[Result]:
        """Record the call and return the queued results.

        Args:
            data: The event data (ignored).
            pipelines: The pipelines, by folder.

        Returns:
            The next queued results.
        """
        calls.append(dict(pipelines))
        return queue.pop(0)

    monkeypatch.setattr(
        "hww_dashboard.service.handle_upload", fake_handle_upload
    )
    return queue


class TestIngestUpload:
    """ingest_upload(): the pipeline that reads the upload's folder."""

    def test_py_common_is_given_every_folders_pipeline(
        self, uploads: list[list[Result]], calls: list[dict[str, Any]]
    ) -> None:
        """handle_upload picks the folder's pipeline; it gets them all.

        Args:
            uploads: Queue of handle_upload results.
            calls: What each handle_upload call was given.
        """
        uploads.append([result(Outcome.LOADED)])

        results = service.ingest_upload(
            event("hww/signups/monitoring.xlsx"), PIPELINES
        )

        assert len(results) == 1
        assert calls == [PIPELINES]

    def test_ignored_event_returns_nothing(
        self, uploads: list[list[Result]], calls: list[dict[str, Any]]
    ) -> None:
        """An event handle_upload ignores gives no results.

        Args:
            uploads: Queue of handle_upload results.
            calls: What each handle_upload call was given.
        """
        uploads.append([])

        assert service.ingest_upload({}, PIPELINES) == []
        assert len(calls) == 1


class TestHandle:
    """handle(): ingest the folder, then rebuild if nothing went wrong."""

    def test_ignored_event_does_nothing(
        self, uploads: list[list[Result]]
    ) -> None:
        """No results (another bucket, no pipeline): no rebuild.

        Args:
            uploads: Queue of handle_upload results.
        """
        uploads.append([])
        rebuilt: list[Path] = []

        assert service.handle({}, Path("c.toml"), rebuilt.append) == (
            "ignored"
        )
        assert rebuilt == []

    def test_quarantine_stops_the_rebuild(
        self,
        uploads: list[list[Result]],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A quarantined file keeps the old tables and logs an error.

        Args:
            uploads: Queue of handle_upload results.
            caplog: Captures the log.
        """
        uploads.append([result(Outcome.QUARANTINED, ["Missing column 'X'"])])
        rebuilt: list[Path] = []

        outcome = service.handle(WAS_UPLOAD, Path("c.toml"), rebuilt.append)

        assert outcome == "quarantined"
        assert rebuilt == []
        assert "Missing column 'X'" in caplog.text

    def test_monitoring_quarantine_stops_the_rebuild(
        self, uploads: list[list[Result]]
    ) -> None:
        """A bad Survey info sheet stops both sheets and the rebuild.

        Args:
            uploads: Queue of handle_upload results.
        """
        uploads.append([result(Outcome.QUARANTINED, ["Unexpected columns"])])
        rebuilt: list[Path] = []

        outcome = service.handle(
            event("hww/signups/monitoring.xlsx"),
            Path("c.toml"),
            rebuilt.append,
        )

        assert outcome == "quarantined"
        assert rebuilt == []

    @pytest.mark.parametrize("outcome", [Outcome.LOADED, Outcome.SKIPPED])
    def test_clean_ingest_rebuilds(
        self, uploads: list[list[Result]], outcome: Outcome
    ) -> None:
        """Loaded, or already loaded (a redelivery): the tables rebuild.

        Args:
            uploads: Queue of handle_upload results.
            outcome: The file's outcome.
        """
        uploads.append([result(outcome)])
        rebuilt: list[Path] = []

        assert service.handle(WAS_UPLOAD, Path("c.toml"), rebuilt.append) == (
            "rebuilt"
        )
        assert rebuilt == [Path("c.toml")]

    def test_fixable_rebuild_problem_is_not_retried(
        self, uploads: list[list[Result]]
    ) -> None:
        """An InputError from the pipeline is logged, not raised.

        Args:
            uploads: Queue of handle_upload results.
        """
        uploads.append([result(Outcome.LOADED)])

        def rebuild(path: Path) -> None:
            """Stop as the pipeline does on a fixable problem.

            Args:
                path: The config (ignored).

            Raises:
                InputError: Always.
            """
            raise wrangle.InputError("a mapping is missing")

        assert service.handle(WAS_UPLOAD, Path("c.toml"), rebuild) == (
            "rebuild stopped"
        )

    def test_unexpected_rebuild_error_is_retried(
        self, uploads: list[list[Result]]
    ) -> None:
        """Any other error is raised, so Pub/Sub delivers the event again.

        Args:
            uploads: Queue of handle_upload results.
        """
        uploads.append([result(Outcome.LOADED)])

        def rebuild(path: Path) -> None:
            """Fail as an outage would.

            Args:
                path: The config (ignored).

            Raises:
                RuntimeError: Always.
            """
            raise RuntimeError("BigQuery unavailable")

        with pytest.raises(RuntimeError, match="unavailable"):
            service.handle(WAS_UPLOAD, Path("c.toml"), rebuild)


class TestFolderPipelines:
    """folder_pipelines(): one pipeline per landing folder."""

    def test_keys_are_the_landing_folders(
        self, tmp_path: Path, data_folder: Path
    ) -> None:
        """With no prefix, the monitoring workbook loads both tables.

        Args:
            tmp_path: Folder for the config.
            data_folder: tests/data, whose config is copied.
        """
        text = (data_folder / "config.toml").read_text("utf-8")
        maps = (data_folder.parent.parent / "mappings").as_posix()
        text = text.replace(
            'mappings_folder = "../../mappings"',
            f'mappings_folder = "{maps}"',
        )
        config = tmp_path / "config.toml"
        config.write_text(text, encoding="utf-8")

        pipelines = service.folder_pipelines(config)

        tables = {
            folder: pipeline.warehouse.identity.rsplit(".", 1)[-1]
            for folder, pipeline in pipelines.items()
        }
        assert tables == {
            "signups": "hww_signups+hww_survey",
            "was": "hww_was",
            "peer": "hww_peer",
        }


class TestNewestSourceBucket:
    """A file_pattern source's NewestSource exposes its bucket."""

    def test_passes_through_the_bucket(self) -> None:
        """A GCS-like source's bucket is visible; a local one gives None."""
        gcs_like = SimpleNamespace(bucket_name="landing-dev")
        local = SimpleNamespace()

        def modified(item: SourceItem) -> float:
            """Unused modification time.

            Args:
                item: Ignored.

            Returns:
                0.
            """
            return 0.0

        assert (
            landing.NewestSource(gcs_like, "*.xlsx", modified).bucket_name
            == "landing-dev"
        )
        assert (
            landing.NewestSource(local, "*.xlsx", modified).bucket_name is None
        )
