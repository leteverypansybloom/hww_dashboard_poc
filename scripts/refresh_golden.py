"""Rewrite the golden snapshot from a run on the synthetic inputs.

Run this only after the project owner has agreed an output change:

    python scripts/refresh_golden.py

It runs the pipeline through tests/data/config.toml at the tests' fixed
time, replaces the files in tests/golden/ that differ, and lists them.
Check every line of ``git diff tests/golden`` before committing the
snapshot with the code change. The tests never write to tests/golden/.
"""

import argparse
import shutil
import sys
import tempfile
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from hww_dashboard import wrangle

PROJECT = Path(__file__).resolve().parent.parent
GOLDEN = PROJECT / "tests" / "golden"
CONFIG = PROJECT / "tests" / "data" / "config.toml"
#: The time the tests treat as now (``run_time`` in tests/conftest.py).
RUN_TIME = datetime(2026, 10, 10, 12, 0)
REPORT = "data_quality_report.md"


def snapshot_files(folder: Path) -> dict[str, Path]:
    """Find the files in a folder that belong in the snapshot.

    Args:
        folder: The golden folder or a pipeline output folder.

    Returns:
        File name -> path, for every CSV and the data quality report.
    """
    files = {p.name: p for p in sorted(folder.glob("*.csv"))}
    if (folder / REPORT).exists():
        files[REPORT] = folder / REPORT
    return files


def same_text(first: Path, second: Path) -> bool:
    """Compare two text files, ignoring line endings.

    Args:
        first: One file.
        second: The other file.

    Returns:
        True if their lines are the same.
    """
    return first.read_bytes().replace(b"\r\n", b"\n") == (
        second.read_bytes().replace(b"\r\n", b"\n")
    )


def refresh(golden: Path = GOLDEN, config: Path = CONFIG) -> list[str]:
    """Replace the snapshot files that differ from a fresh run.

    Args:
        golden: The snapshot folder to update.
        config: The frozen config that reads the synthetic inputs.

    Returns:
        One line per file added, changed or removed, e.g.
        ``"changed fact_signup.csv"``. Empty if nothing changed.
    """
    with tempfile.TemporaryDirectory() as scratch:
        output = Path(scratch) / "output"
        wrangle.run(config, output_folder=output, now=RUN_TIME)
        new = snapshot_files(output)
        old = snapshot_files(golden)
        changes = []
        for name in sorted(old.keys() - new.keys()):
            old[name].unlink()
            changes.append(f"removed {name}")
        for name, path in new.items():
            if name not in old:
                changes.append(f"added {name}")
            elif same_text(path, old[name]):
                continue
            else:
                changes.append(f"changed {name}")
            shutil.copyfile(path, golden / name)
    return changes


def main(argv: Sequence[str] | None = None) -> int:
    """Refresh the snapshot and say what changed.

    Args:
        argv: Command-line arguments (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code 0.
    """
    parser = argparse.ArgumentParser(
        description="Rewrite tests/golden/ from a run on the synthetic "
        "inputs, after an agreed output change."
    )
    parser.add_argument(
        "--golden",
        type=Path,
        default=GOLDEN,
        help="snapshot folder to update (default: tests/golden)",
    )
    args = parser.parse_args(argv)
    changes = refresh(args.golden)
    if not changes:
        print("The snapshot already matches the pipeline's output.")
    for line in changes:
        print(line)
    if changes:
        print("Check every line of: git diff tests/golden")
    return 0


if __name__ == "__main__":
    sys.exit(main())
