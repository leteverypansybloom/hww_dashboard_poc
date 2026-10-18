"""Checks on scripts/check_no_real_data.py, the pre-commit data guard."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "check_no_real_data.py"
)


@pytest.fixture(scope="module")
def guard() -> ModuleType:
    """Import the guard as a module, without running it.

    Returns:
        scripts/check_no_real_data.py as a module.
    """
    spec = importlib.util.spec_from_file_location("check_no_real_data", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestProblems:
    """``problems``: which committed paths are refused."""

    @pytest.mark.parametrize(
        "path",
        [
            "output/dim_employer.csv",
            "output\\data_quality_report.md",
            "HWW monitoring and reporting.xlsx",
            "docs/WAS export.XLSM",
            "dim_employer.csv",
            "src/hww_dashboard/extract.csv",
        ],
    )
    def test_possible_real_data_is_refused(
        self, guard: ModuleType, path: str
    ) -> None:
        """Outputs, stray workbooks and stray CSVs are refused by name.

        Args:
            guard: The guard script.
            path: A path that may hold real data.
        """
        found = guard.problems([path])
        assert len(found) == 1
        assert path.replace("\\", "/") in found[0]

    @pytest.mark.parametrize(
        "path",
        [
            "tests/data/inputs/dummy_was_database.xlsx",
            "tests/golden/dim_employer.csv",
            "mappings/sector.csv",
            "src/hww_dashboard/wrangle.py",
            "outputs.md",
        ],
    )
    def test_project_files_pass(self, guard: ModuleType, path: str) -> None:
        """Synthetic workbooks, the snapshot, mappings and code pass.

        Args:
            guard: The guard script.
            path: A path that belongs in the repository.
        """
        assert guard.problems([path]) == []


class TestMain:
    """``main``: the exit code pre-commit acts on."""

    def test_exit_code_says_whether_anything_was_refused(
        self, guard: ModuleType, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Exit 1 and a message for a refused file, 0 for clean files.

        Args:
            guard: The guard script.
            capsys: Captures what the guard prints.
        """
        assert guard.main(["mappings/sector.csv"]) == 0
        assert guard.main(["output/badges.csv"]) == 1
        assert "output/badges.csv" in capsys.readouterr().out
