"""Checks on scripts/refresh_golden.py, which rewrites tests/golden/.

Every test works on a copy of the snapshot; the real one is never
written.
"""

import importlib.util
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType

import pytest

PROJECT = Path(__file__).resolve().parent.parent
SCRIPT = PROJECT / "scripts" / "refresh_golden.py"
GOLDEN = PROJECT / "tests" / "golden"


@pytest.fixture(scope="module")
def script() -> ModuleType:
    """Import the script as a module, without running it.

    Returns:
        scripts/refresh_golden.py as a module.
    """
    spec = importlib.util.spec_from_file_location("refresh_golden", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def golden_copy(tmp_path: Path) -> Path:
    """Copy the snapshot to a folder the test may change.

    Args:
        tmp_path: The test's temporary folder.

    Returns:
        The copy.
    """
    copy = tmp_path / "golden"
    shutil.copytree(GOLDEN, copy)
    return copy


class TestRefresh:
    """``refresh``: bring a snapshot back in line with the pipeline."""

    def test_uses_the_tests_run_time(
        self, script: ModuleType, run_time: datetime
    ) -> None:
        """The snapshot is made at the time the tests treat as now.

        Args:
            script: The refresh script.
            run_time: The tests' fixed run time.
        """
        assert script.RUN_TIME == run_time

    def test_matching_snapshot_is_left_alone(
        self, script: ModuleType, golden_copy: Path
    ) -> None:
        """Nothing is reported or rewritten when nothing differs.

        Args:
            script: The refresh script.
            golden_copy: A copy of the snapshot.
        """
        assert script.refresh(golden_copy) == []

    def test_restores_changed_missing_and_extra_files(
        self, script: ModuleType, golden_copy: Path
    ) -> None:
        """Edited, deleted and stray files are put right, and listed.

        Args:
            script: The refresh script.
            golden_copy: A copy of the snapshot.
        """
        (golden_copy / "dim_date.csv").write_text("edited\n", "utf-8")
        (golden_copy / "badges.csv").unlink()
        (golden_copy / "stray.csv").write_text("x\n", "utf-8")
        changes = script.refresh(golden_copy)
        assert changes == [
            "removed stray.csv",
            "added badges.csv",
            "changed dim_date.csv",
        ]
        for name, path in script.snapshot_files(GOLDEN).items():
            assert script.same_text(path, golden_copy / name), name


class TestMain:
    """``main``: ``python scripts/refresh_golden.py [--golden FOLDER]``."""

    def test_lists_what_it_changed(self, golden_copy: Path) -> None:
        """The script runs on its own and names each file it rewrote.

        Args:
            golden_copy: A copy of the snapshot.
        """
        (golden_copy / "dim_date.csv").write_text("edited\n", "utf-8")
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--golden", str(golden_copy)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "changed dim_date.csv" in result.stdout
