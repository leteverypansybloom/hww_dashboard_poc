"""Safety net: the pipeline must write exactly the saved snapshot.

The snapshot in tests/golden/ was taken before the code was tidied up:
every output CSV, and the data quality report of a run at 12:00 on
10 October 2026 (the report shows the run time, and warns about dates
after it). A style change or refactor must not change a single byte of
them. If an output change is intended, check the difference by hand,
then refresh the snapshot with

    HWW_UPDATE_GOLDEN=1 python -m pytest tests/test_golden.py

(in PowerShell, run ``$env:HWW_UPDATE_GOLDEN=1`` first) and commit the
new files in tests/golden/ together with the code change.

The run reads the synthetic inputs through tests/data/config.toml, so
this test is unaffected when config.toml moves to the real data. It does
use the live mappings/ folder: adding a mapping that changes the
synthetic output is an output change.
"""

import difflib
import os
import shutil
from pathlib import Path

import pytest

GOLDEN = Path(__file__).resolve().parent / "golden"
REPORT = "data_quality_report.md"


def read_lines(path: Path) -> list[str]:
    """Read a text file as lines, whatever its line endings.

    Git may convert line endings on checkout, so they are not compared.

    Args:
        path: The file.

    Returns:
        Its lines, without line endings.
    """
    text = path.read_bytes().decode("utf-8")
    return text.replace("\r\n", "\n").split("\n")


def snapshot_files() -> list[str]:
    """List the files in the snapshot.

    Returns:
        The CSVs in tests/golden/, sorted, then the report.
    """
    return [*sorted(p.name for p in GOLDEN.glob("*.csv")), REPORT]


@pytest.fixture(scope="module")
def fresh_output(pipeline_output: Path) -> Path:
    """The pipeline's output, after refreshing the snapshot if asked to.

    With ``HWW_UPDATE_GOLDEN=1`` the snapshot is replaced by this output
    first, so the comparisons pass and git shows what changed.

    Returns:
        The folder written by one run on the synthetic inputs.
    """
    if os.environ.get("HWW_UPDATE_GOLDEN") == "1":
        for old in GOLDEN.glob("*.csv"):
            old.unlink()
        for new in pipeline_output.glob("*.csv"):
            shutil.copy(new, GOLDEN / new.name)
        shutil.copy(pipeline_output / REPORT, GOLDEN / REPORT)
    return pipeline_output


class TestGoldenSnapshot:
    """The pipeline's output matches tests/golden/ exactly."""

    def test_same_set_of_csv_files(self, fresh_output: Path) -> None:
        """The run writes exactly the tables in the snapshot."""
        made = sorted(p.name for p in fresh_output.glob("*.csv"))
        saved = sorted(p.name for p in GOLDEN.glob("*.csv"))
        assert made == saved

    @pytest.mark.parametrize("name", snapshot_files())
    def test_file_identical_to_snapshot(
        self, fresh_output: Path, name: str
    ) -> None:
        """Each table, and the report, matches its snapshot line for line.

        Args:
            fresh_output: The folder written by the run.
            name: A file name in tests/golden/.
        """
        expected = read_lines(GOLDEN / name)
        actual = read_lines(fresh_output / name)
        if actual != expected:
            lines = difflib.unified_diff(
                expected, actual, "golden/" + name, "new/" + name, lineterm=""
            )
            diff = "\n".join(list(lines)[:40])
            pytest.fail(f"{name} differs from the snapshot:\n{diff}")
