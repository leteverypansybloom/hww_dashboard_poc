"""Checks on scripts/update_constraints.py, which writes constraints.txt.

Only the parts that need no network are tested here: reading the
requirements and combining the versions pip resolved.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from packaging.requirements import Requirement

PROJECT = Path(__file__).resolve().parent.parent
SCRIPT = PROJECT / "scripts" / "update_constraints.py"


@pytest.fixture(scope="module")
def script() -> ModuleType:
    """Import the script as a module, without running it.

    Returns:
        scripts/update_constraints.py as a module.
    """
    spec = importlib.util.spec_from_file_location("update_constraints", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestRequirements:
    """``requirements``: the runtime requirements in pyproject.toml."""

    def test_includes_the_runtime_extras(self, script: ModuleType) -> None:
        """The pipeline, dashboard and BigQuery packages are all pinned.

        Args:
            script: The constraints script.
        """
        names = {Requirement(r).name for r in script.requirements()}
        assert {
            "pandas",
            "openpyxl",
            "streamlit",
            "plotly",
            "google-cloud-bigquery",
        } <= names


class TestMergePins:
    """``merge_pins``: one constraints file for every platform."""

    def test_same_version_everywhere_gives_one_pin(
        self, script: ModuleType
    ) -> None:
        """A package resolved alike on every platform is pinned once.

        Args:
            script: The constraints script.
        """
        resolved = {
            ("3.11", "linux"): {"pandas": "3.0.6"},
            ("3.11", "windows"): {"pandas": "3.0.6"},
            ("3.13", "linux"): {"pandas": "3.0.6"},
        }
        assert script.merge_pins(resolved) == ["pandas==3.0.6"]

    def test_versions_that_differ_by_python_get_markers(
        self, script: ModuleType
    ) -> None:
        """Each Python gets its own pin when they need different versions.

        Args:
            script: The constraints script.
        """
        resolved = {
            ("3.11", "linux"): {"numpy": "2.4.6"},
            ("3.13", "linux"): {"numpy": "2.5.4"},
        }
        assert script.merge_pins(resolved) == [
            'numpy==2.4.6; python_version == "3.11"',
            'numpy==2.5.4; python_version == "3.13"',
        ]

    def test_versions_that_differ_by_platform_are_refused(
        self, script: ModuleType
    ) -> None:
        """Linux and Windows disagreeing on one Python is an error.

        Args:
            script: The constraints script.
        """
        resolved = {
            ("3.13", "linux"): {"pywin": "1"},
            ("3.13", "windows"): {"pywin": "2"},
        }
        with pytest.raises(ValueError, match="differs between platforms"):
            script.merge_pins(resolved)


class TestConstraintsFile:
    """The committed constraints.txt."""

    def test_pins_every_runtime_requirement(self, script: ModuleType) -> None:
        """Each requirement in pyproject.toml has a pin in constraints.txt.

        Args:
            script: The constraints script.
        """
        lines = (PROJECT / "constraints.txt").read_text("utf-8").splitlines()
        pinned = {
            Requirement(line).name.lower()
            for line in lines
            if line and not line.startswith("#")
        }
        for requirement in script.requirements():
            assert Requirement(requirement).name.lower() in pinned
