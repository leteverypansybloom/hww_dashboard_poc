"""Read-only checks against the frozen synthetic pipeline snapshot."""

import difflib
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
    """Return pipeline output without ever refreshing golden files.

    Args:
        pipeline_output: Shared output from the frozen synthetic run.

    Returns:
        The generated output folder, leaving the snapshot untouched.
    """
    return pipeline_output


class TestRun:
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
