"""Checks on run logging: console lines, the saved log and JSON lines."""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hww_dashboard import logs

LOG = logging.getLogger("hww_dashboard.tests")


def crash() -> None:
    """Raise an error whose message stands in for a cell value.

    The message is built at run time, so the source line shown in a
    stack doesn't contain it.

    Raises:
        KeyError: Always.
    """
    raise KeyError(" ".join(["Org", "11", "cell"]))


class TestNewRunId:
    """``new_run_id``: an id for one run that sorts by time."""

    def test_utc_time_then_random_hex(self) -> None:
        """The id starts with the UTC start time."""
        moment = datetime(2026, 10, 18, 9, 15, 2, tzinfo=UTC)
        run_id = logs.new_run_id(moment)
        assert run_id.startswith("20261018T091502Z-")
        assert len(run_id) == len("20261018T091502Z-") + 6

    def test_two_runs_at_the_same_moment_differ(self) -> None:
        """The random part keeps ids apart within one second."""
        moment = datetime(2026, 10, 18, tzinfo=UTC)
        assert logs.new_run_id(moment) != logs.new_run_id(moment)


class TestLogFormat:
    """``log_format``: text unless HWW_LOG_FORMAT says json."""

    @pytest.mark.parametrize(
        ("value", "mode"), [(None, "text"), ("", "text"), (" JSON ", "json")]
    )
    def test_reads_the_environment(
        self, monkeypatch: pytest.MonkeyPatch, value: str | None, mode: str
    ) -> None:
        """Unset or blank means text; the value ignores case and spaces.

        Args:
            monkeypatch: Sets the environment variable.
            value: The variable's value, or None for unset.
            mode: The expected format.
        """
        if value is None:
            monkeypatch.delenv(logs.FORMAT_VARIABLE, raising=False)
        else:
            monkeypatch.setenv(logs.FORMAT_VARIABLE, value)
        assert logs.log_format() == mode

    def test_unknown_format_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Any other value names the variable in the error.

        Args:
            monkeypatch: Sets the environment variable.
        """
        monkeypatch.setenv(logs.FORMAT_VARIABLE, "xml")
        with pytest.raises(ValueError, match="HWW_LOG_FORMAT"):
            logs.log_format()


class TestConfigureLogging:
    """``configure_logging`` and ``close_logging``."""

    def test_text_console_is_one_line_and_the_file_has_details(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Tracebacks go to the log file, never to the console.

        Args:
            tmp_path: Holds the log file.
            capsys: Captures the console.
        """
        log_file = tmp_path / "logs" / "run.log"
        handlers = logs.configure_logging("run-1", "text", log_file)
        try:
            LOG.info("Read %d rows", 3)
            try:
                crash()
            except KeyError:
                LOG.exception("Unexpected error")
        finally:
            logs.close_logging(handlers)
        console = capsys.readouterr().err
        saved = log_file.read_text("utf-8")
        assert "INFO    Read 3 rows" in console
        assert "ERROR   Unexpected error" in console
        assert "Traceback" not in console
        assert "Read 3 rows" in saved
        assert "Traceback" in saved

    def test_json_lines_leave_out_error_messages(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An error's type and stack are logged, its message is not.

        Args:
            capsys: Captures the console.
        """
        handlers = logs.configure_logging("run-2", "json")
        try:
            try:
                crash()
            except KeyError:
                LOG.exception("Unexpected error")
        finally:
            logs.close_logging(handlers)
        line = capsys.readouterr().err.strip().splitlines()[-1]
        entry = json.loads(line)
        assert entry["severity"] == "ERROR"
        assert entry["message"] == "Unexpected error"
        assert entry["run_id"] == "run-2"
        assert entry["error_type"] == "KeyError"
        assert any("in crash" in frame for frame in entry["stack"])
        assert "Org 11 cell" not in line

    def test_closing_detaches_the_handlers(self) -> None:
        """Nothing is left attached after a run."""
        package = logging.getLogger(logs.PACKAGE)
        before = list(package.handlers)
        logs.close_logging(logs.configure_logging("run-3"))
        assert package.handlers == before


class TestPruneLogs:
    """``prune_logs``: keep the newest run logs only."""

    def test_keeps_the_newest_and_other_files(self, tmp_path: Path) -> None:
        """The oldest logs go; files that aren't logs stay.

        Args:
            tmp_path: The log folder.
        """
        names = [f"2026101{n}T000000Z-aaaaaa.log" for n in range(5)]
        for name in names:
            (tmp_path / name).write_text("x", "utf-8")
        (tmp_path / "notes.txt").write_text("keep", "utf-8")
        removed = logs.prune_logs(tmp_path, keep=2)
        assert [p.name for p in removed] == names[:3]
        assert sorted(p.name for p in tmp_path.iterdir()) == [
            *names[3:],
            "notes.txt",
        ]
