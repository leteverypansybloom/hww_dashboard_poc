"""Logging for pipeline runs: readable lines, a saved log, or JSON.

:func:`hww_dashboard.wrangle.main` sets this up once per run.

- **Text** (the default): the console shows one line per message, with
  the time and level, and the run's log file gets every message,
  including the traceback of an unexpected error.
- **JSON** (``HWW_LOG_FORMAT=json``, set in GCP): the console gets one
  JSON object per line, which Cloud Logging turns into a structured
  entry with ``severity``, ``message`` and ``run_id``. An unexpected
  error carries its type and the code it passed through, but not its
  own message, which could quote data. There is no log file.

Log lines name files, sheets, columns and counts, never cell values.
"""

import json
import logging
import os
import secrets
import sys
import traceback
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

#: The package logger; every module logs below it.
PACKAGE = "hww_dashboard"
#: The environment variable that picks the format: "text" or "json".
FORMAT_VARIABLE = "HWW_LOG_FORMAT"
#: How many run logs a log folder keeps.
KEEP_LOGS = 20
LINE = "%(asctime)s %(levelname)-7s %(message)s"
TIME = "%Y-%m-%d %H:%M:%S"


def new_run_id(now: datetime | None = None) -> str:
    """Make an id for one run: its UTC start time and six random hex.

    Args:
        now: The start time. Defaults to now; a time without a time
            zone is taken as local time.

    Returns:
        For example ``20261018T091502Z-3fa2c1``. Ids sort by time.
    """
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    return f"{moment:%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"


def log_format() -> str:
    """Read the log format from the environment.

    Returns:
        ``"text"`` (the default) or ``"json"``.

    Raises:
        ValueError: ``HWW_LOG_FORMAT`` has any other value.
    """
    mode = os.environ.get(FORMAT_VARIABLE, "text").strip().lower() or "text"
    if mode not in ("text", "json"):
        raise ValueError(
            f"{FORMAT_VARIABLE} must be 'text' or 'json', not {mode!r}."
        )
    return mode


class OneLineFormatter(logging.Formatter):
    """Text lines without tracebacks, for the console."""

    def format(self, record: logging.LogRecord) -> str:
        """Format a record as one line, leaving out any traceback.

        Args:
            record: The log record. It is restored unchanged, because
                other handlers format it too.

        Returns:
            The line.
        """
        saved = record.exc_info, record.exc_text, record.stack_info
        record.exc_info, record.exc_text, record.stack_info = None, None, None
        try:
            return super().format(record)
        finally:
            record.exc_info, record.exc_text, record.stack_info = saved


class JsonFormatter(logging.Formatter):
    """One JSON object per line, in Cloud Logging's structured format."""

    def __init__(self, run_id: str) -> None:
        """Remember the run id that every line carries.

        Args:
            run_id: From :func:`new_run_id`.
        """
        super().__init__()
        self.run_id = run_id

    def format(self, record: logging.LogRecord) -> str:
        """Format a record as a JSON object.

        Args:
            record: The log record.

        Returns:
            One line of JSON with time, severity, message, logger and
            run_id; for an error, also its type and stack, but not its
            message.
        """
        entry: dict[str, object] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "run_id": self.run_id,
        }
        if record.exc_info and record.exc_info[1] is not None:
            error = record.exc_info[1]
            entry["error_type"] = type(error).__name__
            # The frames show code, not data. The error's own message
            # could quote a cell, so it is left out.
            entry["stack"] = traceback.format_list(
                traceback.extract_tb(error.__traceback__)
            )
        return json.dumps(entry, ensure_ascii=False)


def configure_logging(
    run_id: str, mode: str = "text", log_file: Path | None = None
) -> list[logging.Handler]:
    """Send the package's log to the console and, in text mode, a file.

    Args:
        run_id: The run's id, which JSON lines carry.
        mode: ``"text"`` or ``"json"``, as from :func:`log_format`.
        log_file: In text mode, a file that gets every message,
            tracebacks included. Its folder is created if needed.

    Returns:
        The handlers added, for :func:`close_logging`.
    """
    package = logging.getLogger(PACKAGE)
    package.setLevel(logging.INFO)
    console = logging.StreamHandler(sys.stderr)
    if mode == "json":
        console.setFormatter(JsonFormatter(run_id))
    else:
        console.setFormatter(OneLineFormatter(LINE, TIME))
    handlers: list[logging.Handler] = [console]
    if mode == "text" and log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        saved = logging.FileHandler(log_file, encoding="utf-8")
        saved.setFormatter(logging.Formatter(LINE, TIME))
        handlers.append(saved)
    for handler in handlers:
        package.addHandler(handler)
    return handlers


def close_logging(handlers: Iterable[logging.Handler]) -> None:
    """Detach and close the handlers :func:`configure_logging` added.

    Args:
        handlers: The handlers to remove.
    """
    package = logging.getLogger(PACKAGE)
    for handler in handlers:
        package.removeHandler(handler)
        handler.close()


def prune_logs(folder: Path, keep: int = KEEP_LOGS) -> list[Path]:
    """Delete all but the newest run logs in a folder.

    Log files are named after their run id, so name order is time
    order.

    Args:
        folder: The log folder.
        keep: How many of the newest logs to keep.

    Returns:
        The files deleted.
    """
    logs = sorted(folder.glob("*.log"))
    old = logs[: max(0, len(logs) - keep)]
    for path in old:
        path.unlink(missing_ok=True)
    return old
