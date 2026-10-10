"""Safety net: the pipeline must write exactly the same CSVs as the saved snapshot.

The snapshot in tests/golden/ was taken before the code was tidied up. A style change or
refactor must not change a single byte of output. If an output change is intended, check
the difference by hand, then refresh the snapshot with:

    HWW_UPDATE_GOLDEN=1 python -m pytest tests/test_golden.py      (bash)
    $env:HWW_UPDATE_GOLDEN=1; python -m pytest tests/test_golden.py  (PowerShell)

and commit the new files in tests/golden/ together with the code change.
"""

import difflib
import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = Path(__file__).resolve().parent / "golden"
sys.path.insert(0, str(ROOT))

import wrangle


def read_lines(path: Path) -> list[str]:
    """Read a CSV as lines, ignoring Windows/Unix line-ending differences (git may convert them)."""
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n").split("\n")


@pytest.fixture(scope="module")
def fresh_output(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Run the whole pipeline once into a temporary folder."""
    folder = tmp_path_factory.mktemp("golden_check")
    wrangle.run(ROOT / "config.toml", output_folder=folder)
    if os.environ.get("HWW_UPDATE_GOLDEN") == "1":
        for old in GOLDEN.glob("*.csv"):
            old.unlink()
        for new in folder.glob("*.csv"):
            shutil.copy(new, GOLDEN / new.name)
    return folder


def test_same_set_of_csv_files(fresh_output: Path) -> None:
    """The run writes exactly the tables in the snapshot, no more and no fewer."""
    made = sorted(p.name for p in fresh_output.glob("*.csv"))
    saved = sorted(p.name for p in GOLDEN.glob("*.csv"))
    assert made == saved


@pytest.mark.parametrize("name", sorted(p.name for p in GOLDEN.glob("*.csv")))
def test_csv_identical_to_snapshot(fresh_output: Path, name: str) -> None:
    """Each table matches its snapshot line for line (line endings aside)."""
    expected = read_lines(GOLDEN / name)
    actual = read_lines(fresh_output / name)
    if actual != expected:
        diff = "\n".join(
            list(
                difflib.unified_diff(expected, actual, "golden/" + name, "new/" + name, lineterm="")
            )[:40]
        )
        pytest.fail(f"{name} differs from the snapshot:\n{diff}")
