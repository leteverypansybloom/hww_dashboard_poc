"""Checks on the upload-triggered Cloud Run service (service.py).

py-common's handle_upload, which ingests the upload's folder, is
replaced by a stand-in returning chosen results, so these tests check
the service's own decisions: when to rebuild the tables, and which
problems are retried.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("py_common")

from py_common.model import Outcome, Result, SourceItem  # noqa: E402

from hww_dashboard import landing, service, wrangle  # noqa: E402


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


@pytest.fixture
def uploads(monkeypatch: pytest.MonkeyPatch) -> list[list[Result]]:
    """Replace handle_upload with one returning the next listed results.

    Args:
        monkeypatch: Replaces handle_upload and the pipelines.

    Returns:
        A list the test fills with handle_upload's next return value.
    """
    queue: list[list[Result]] = []

    def fake_handle_upload(data: Any, pipelines: Any) -> list[Result]:
        """Return the queued results.

        Args:
            data: The event data (ignored).
            pipelines: The pipelines (ignored).

        Returns:
            The next queued results.
        """
        return queue.pop(0)

    monkeypatch.setattr(
        "hww_dashboard.service.handle_upload", fake_handle_upload
    )
    monkeypatch.setattr(
        "hww_dashboard.service.folder_pipelines", lambda path: {}
    )
    return queue


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

        outcome = service.handle({}, Path("c.toml"), rebuilt.append)

        assert outcome == "quarantined"
        assert rebuilt == []
        assert "Missing column 'X'" in caplog.text

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

        assert service.handle({}, Path("c.toml"), rebuilt.append) == (
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

        assert service.handle({}, Path("c.toml"), rebuild) == (
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
            service.handle({}, Path("c.toml"), rebuild)


class TestFolderPipelines:
    """folder_pipelines(): one pipeline per landing folder."""

    def test_keys_are_the_landing_folders(
        self, tmp_path: Path, data_folder: Path
    ) -> None:
        """With no prefix, each folder is the source's name.

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

        assert sorted(pipelines) == sorted(wrangle.SOURCES)


class TestNewestSourceBucket:
    """The survey's NewestSource exposes its bucket for the event check."""

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
