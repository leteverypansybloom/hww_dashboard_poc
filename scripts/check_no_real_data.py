"""Refuse files that may hold real data: a pre-commit hook.

    python scripts/check_no_real_data.py FILE ...

Fails if a file is in output/, is a spreadsheet outside
tests/data/inputs/, or is a CSV outside mappings/ and tests/. Real
workbooks stay outside the repository and real tables in the ignored
output/ folder; this catches a copy added by mistake. pre-commit passes
the names of the files being committed.
"""

import csv
import sys
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

SPREADSHEETS = {".xls", ".xlsb", ".xlsm", ".xlsx", ".ods"}
SPREADSHEET_FOLDERS = ("tests/data/inputs/",)
CSV_FOLDERS = ("mappings/", "tests/")


def problems(paths: Sequence[str]) -> list[str]:
    """Find the files that must not be committed.

    Args:
        paths: File paths relative to the repository root, with either
            kind of slash.

    Returns:
        One message per refused file, naming it and saying why.
    """
    found = []
    for raw in paths:
        path = PurePosixPath(raw.replace("\\", "/"))
        name = path.as_posix()
        suffix = path.suffix.lower()
        if path.parts and path.parts[0] in {
            "output",
            "store",
            "landed",
            "landing",
            "logs",
        }:
            found.append(f"{name}: data and log folders are never committed.")
        elif suffix in SPREADSHEETS and not name.startswith(
            SPREADSHEET_FOLDERS
        ):
            found.append(
                f"{name}: keep workbooks outside the repository; synthetic "
                "test workbooks go in tests/data/inputs/."
            )
        elif suffix == ".csv" and not name.startswith(CSV_FOLDERS):
            found.append(
                f"{name}: CSV files belong in mappings/ or tests/; real "
                "tables stay in output/, which git ignores."
            )
        elif suffix in {".jsonl", ".ndjson", ".log"} and not name.startswith(
            "tests/"
        ):
            found.append(f"{name}: keep source exports and logs outside Git.")
        elif suffix == ".json" and not name.startswith(
            ("tests/", "src/hww_dashboard/schema/", "dataform/")
        ):
            found.append(f"{name}: JSON data belongs outside the repository.")
    return found


def main(argv: Sequence[str] | None = None) -> int:
    """Print a line for each refused file.

    Args:
        argv: File paths (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code: 1 if any file was refused, otherwise 0.
    """
    paths = list(sys.argv[1:] if argv is None else argv)
    if paths == ["--stdin0"]:
        paths = [
            path
            for path in sys.stdin.buffer.read().decode().split("\0")
            if path
        ]
    found = problems(paths)
    if "mappings/org_overrides.csv" in paths:
        with Path("mappings/org_overrides.csv").open(
            encoding="utf-8-sig", newline=""
        ) as stream:
            if any(csv.DictReader(stream)):
                found.append(
                    "mappings/org_overrides.csv: keep organisation overrides "
                    "in a private file or table, outside Git."
                )
    for message in found:
        print(message)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
