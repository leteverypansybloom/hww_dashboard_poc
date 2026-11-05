"""Mapping CSV validation in the Dataform reference-data builder."""

import shutil
import subprocess
from pathlib import Path

import pytest


class TestBuildReferenceData:
    """Blank physical lines and empty mapping records are distinct."""

    @pytest.mark.parametrize(
        ("suffix", "valid"), [("\n", True), (",\n", False)]
    )
    def test_empty_mapping_record_is_refused(
        self, tmp_path: Path, project_folder: Path, suffix: str, valid: bool
    ) -> None:
        """An empty CSV record cannot disappear during reference generation.

        Args:
            tmp_path: Synthetic reference project folder.
            project_folder: Reviewed project source.
            suffix: Extra synthetic CSV line.
            valid: Whether the line is an ignorable physical blank.
        """
        node = shutil.which("node")
        if node is None:
            pytest.skip("Node.js is needed for the reference-data builder")
        for folder in ("mappings", "src/hww_dashboard/schema"):
            shutil.copytree(project_folder / folder, tmp_path / folder)
        for name in (
            "dataform/scripts/build_reference_data.js",
            "dataform/includes/reference_data.js",
            "tests/data/identifier_cases.json",
        ):
            target = tmp_path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(project_folder / name, target)
        mapping = tmp_path / "mappings/sector.csv"
        mapping.write_bytes(mapping.read_bytes() + suffix.encode())
        result = subprocess.run(
            [node, "scripts/build_reference_data.js", "--check"],
            cwd=tmp_path / "dataform",
            capture_output=True,
            text=True,
            check=False,
        )
        assert (result.returncode == 0) is valid, result.stderr
        if not valid:
            assert "no mapping values" in result.stderr
