"""Refuse files that may hold real data: a pre-commit hook.

    python scripts/check_no_real_data.py FILE ...

Fails if a file is in output/, is a spreadsheet outside
tests/data/inputs/, or is a CSV outside mappings/ and tests/. Real
workbooks stay outside the repository and real tables in the ignored
output/ folder; this catches a copy added by mistake. pre-commit passes
the names of the files being committed.
"""

import sys
from collections.abc import Sequence
from pathlib import PurePosixPath

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
        if name == "output" or name.startswith("output/"):
            found.append(
                f"{name}: output/ holds real tables and is never committed."
            )
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
    return found


def main(argv: Sequence[str] | None = None) -> int:
    """Print a line for each refused file.

    Args:
        argv: File paths (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code: 1 if any file was refused, otherwise 0.
    """
    found = problems(sys.argv[1:] if argv is None else argv)
    for message in found:
        print(message)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
