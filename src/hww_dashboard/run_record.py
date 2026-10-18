"""The run record: what produced a set of outputs.

Every run that publishes its outputs writes a record beside them
(``run_record.json``), so anyone can tell later which files, settings,
mappings and code made the tables. It names files and gives their
sizes, times and SHA-256 checksums, with row counts and library
versions. It never holds a cell value, so it is safe to keep and share,
like py-common's audit records.
"""

import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: The record's file name, next to the output tables.
RECORD_NAME = "run_record.json"
#: Raise when the record's layout changes, so readers can tell.
RECORD_VERSION = 1
#: Set in a container image, where there is no git checkout.
COMMIT_VARIABLE = "HWW_GIT_COMMIT"
LIBRARIES = ("pandas", "numpy", "openpyxl")

Record = dict[str, Any]


def sha256_bytes(data: bytes) -> str:
    """Checksum some bytes.

    Args:
        data: The bytes, e.g. a table's CSV text encoded as UTF-8.

    Returns:
        Their SHA-256, as 64 hex digits.
    """
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    """Checksum a file.

    Args:
        path: The file.

    Returns:
        Its SHA-256, as 64 hex digits.
    """
    return sha256_bytes(path.read_bytes())


def file_facts(path: Path) -> dict[str, Any]:
    """Describe a file without reading out its contents.

    Args:
        path: The file.

    Returns:
        Its name, size in bytes, last-modified time (UTC, ISO 8601) and
        SHA-256.
    """
    stat = path.stat()
    modified = datetime.fromtimestamp(stat.st_mtime, UTC)
    return {
        "file": path.name,
        "bytes": stat.st_size,
        "modified": modified.isoformat(timespec="seconds"),
        "sha256": sha256_file(path),
    }


def utc_iso(moment: datetime | None = None) -> str:
    """Write a time as ISO 8601 in UTC, to the second.

    Args:
        moment: The time (defaults to now). A time without a time zone
            is taken as local time.

    Returns:
        For example ``2026-10-18T09:15:02+00:00``.
    """
    when = (moment or datetime.now(UTC)).astimezone(UTC)
    return when.isoformat(timespec="seconds")


def git_commit(folder: Path) -> tuple[str, bool | None]:
    """Find the commit the code was run from.

    Args:
        folder: A folder inside the code's git checkout.

    Returns:
        (commit, uncommitted changes). The commit comes from
        ``HWW_GIT_COMMIT`` when it is set (then whether there were
        changes is None), else from git; ``"unknown"`` when neither
        works.
    """
    commit = os.environ.get(COMMIT_VARIABLE, "").strip()
    if commit:
        return commit, None

    def git(*args: str) -> str | None:
        """Run git in the folder.

        Args:
            *args: Git's arguments.

        Returns:
            Its output, or None if git failed or isn't installed.
        """
        try:
            done = subprocess.run(
                ["git", "-C", str(folder), *args],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return done.stdout.strip() if done.returncode == 0 else None

    head = git("rev-parse", "HEAD")
    if not head:
        return "unknown", None
    status = git("status", "--porcelain", "--untracked-files=no")
    return head, (bool(status) if status is not None else None)


def versions() -> dict[str, str]:
    """Name the versions the run used.

    Returns:
        Python, the platform, and the pipeline's main libraries.
    """
    found = {
        "python": platform.python_version(),
        "platform": platform.platform(),
    }
    for library in LIBRARIES:
        try:
            found[library] = importlib.metadata.version(library)
        except importlib.metadata.PackageNotFoundError:
            found[library] = "not installed"
    return found


def package_version() -> str:
    """Give the installed version of this package.

    Returns:
        The version in pyproject.toml, or ``"unknown"`` if the package
        isn't installed.
    """
    try:
        return importlib.metadata.version("hww-dashboard")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def start_record(
    run_id: str,
    started: datetime,
    config_path: Path,
    mapping_files: Iterable[Path],
) -> Record:
    """Begin the record of a run.

    Args:
        run_id: The run's id.
        started: When the run started.
        config_path: The config file.
        mapping_files: The mapping CSVs the run read.

    Returns:
        The record so far; the pipeline adds inputs, outputs and what
        needs attention.
    """
    commit, changed = git_commit(Path(__file__).resolve().parent)
    return {
        "record_version": RECORD_VERSION,
        "run_id": run_id,
        "started_at": utc_iso(started),
        "code": {
            "package": "hww-dashboard",
            "version": package_version(),
            "git_commit": commit,
            "uncommitted_changes": changed,
        },
        "environment": versions(),
        "config": file_facts(config_path),
        "mappings": [file_facts(path) for path in sorted(mapping_files)],
    }


def write_record(path: Path, record: Record) -> None:
    """Save a record as JSON, with LF line endings.

    Args:
        path: Where to write it.
        record: The record.
    """
    text = json.dumps(record, indent=2, ensure_ascii=False) + "\n"
    path.write_bytes(text.encode("utf-8"))
