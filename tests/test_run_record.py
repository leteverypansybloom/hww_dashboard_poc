"""Checks on the run record published with every set of outputs."""

import hashlib
import importlib.metadata
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from hww_dashboard import run_record, wrangle


def sha256(path: Path) -> str:
    """Checksum a file independently of the code under test.

    Args:
        path: The file.

    Returns:
        Its SHA-256 in hex.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def record(pipeline_output: Path) -> dict[str, Any]:
    """The record of one run on the synthetic inputs.

    Args:
        pipeline_output: The folder that run wrote.

    Returns:
        run_record.json, parsed.
    """
    path = pipeline_output / run_record.RECORD_NAME
    data: dict[str, Any] = json.loads(path.read_text("utf-8"))
    return data


class TestRun:
    """``run``: the record names everything that made the outputs."""

    def test_inputs_are_the_files_read(
        self, record: dict[str, Any], data_folder: Path
    ) -> None:
        """Each workbook is named, with its sheet, rows and checksum.

        Args:
            record: The run record.
            data_folder: Holds the synthetic inputs.
        """
        inputs = {entry["source"]: entry for entry in record["inputs"]}
        assert list(inputs) == [
            "Account signups",
            "Survey info",
            "WAS database",
            "Peer mentoring",
        ]
        assert inputs["WAS database"]["sheet"] == "query"
        assert inputs["Account signups"]["rows"] == 200
        for entry in inputs.values():
            path = data_folder / "inputs" / entry["file"]
            assert entry["sha256"] == sha256(path)
            assert entry["bytes"] == path.stat().st_size

    def test_config_and_mappings_are_checksummed(
        self,
        record: dict[str, Any],
        fixture_config: Path,
        project_folder: Path,
    ) -> None:
        """The config and every mapping file are named with checksums.

        Args:
            record: The run record.
            fixture_config: The config the run used.
            project_folder: Holds the mappings.
        """
        assert record["config"]["sha256"] == sha256(fixture_config)
        maps = sorted((project_folder / "mappings").glob("*.csv"))
        assert [m["file"] for m in record["mappings"]] == [
            p.name for p in maps
        ]
        for entry, path in zip(record["mappings"], maps, strict=True):
            assert entry["sha256"] == sha256(path)

    def test_code_and_library_versions(self, record: dict[str, Any]) -> None:
        """The package version, commit and libraries are recorded.

        Args:
            record: The run record.
        """
        assert record["record_version"] == run_record.RECORD_VERSION
        assert record["code"]["version"] == importlib.metadata.version(
            "hww-dashboard"
        )
        commit = record["code"]["git_commit"]
        assert commit == "unknown" or re.fullmatch(r"[0-9a-f]{40}", commit)
        assert {"python", "pandas", "openpyxl"} <= set(record["environment"])

    def test_what_needs_attention(self, record: dict[str, Any]) -> None:
        """The record repeats the report's count of things to act on.

        Args:
            record: The run record.
        """
        assert record["attention"] == {"unmapped": 1}

    def test_holds_no_cell_values(
        self, record: dict[str, Any], pipeline_output: Path
    ) -> None:
        """No organisation name or answer from the outputs appears.

        Args:
            record: The run record.
            pipeline_output: The run's tables.
        """
        text = json.dumps(record)
        employers = pd.read_csv(pipeline_output / "dim_employer.csv")
        answers = pd.read_csv(pipeline_output / "fact_survey_answer.csv")
        for value in [*employers["employer_name"], *answers["answer"]]:
            assert f'"{value}"' not in text


class TestWriteOutputs:
    """``write_outputs``: the record is published with the tables."""

    def test_output_checksums_match_the_files(
        self, record: dict[str, Any], pipeline_output: Path
    ) -> None:
        """Each output's checksum is that of the published file.

        Args:
            record: The run record.
            pipeline_output: The run's tables.
        """
        assert record["outcome"] == "published"
        for name, facts in record["outputs"].items():
            suffix = ".md" if name == "data_quality_report" else ".csv"
            assert facts["sha256"] == sha256(pipeline_output / (name + suffix))
        assert record["outputs"]["dim_date"]["rows"] == 730

    def test_no_record_without_one(
        self, tmp_path: Path, run_time: datetime
    ) -> None:
        """Writing outputs without a record writes no record file.

        Args:
            tmp_path: The output folder's parent.
            run_time: The tests' fixed run time.
        """
        out = tmp_path / "out"
        wrangle.write_outputs(
            {"badges": pd.DataFrame({"badge": ["Award"]})},
            out,
            pd.DataFrame({"event_type": []}),
            wrangle.Report(),
            run_time,
        )
        assert not (out / run_record.RECORD_NAME).exists()


class TestGitCommit:
    """``git_commit``: the commit the code ran from."""

    def test_the_environment_variable_wins(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A commit given to a container image is used as it is.

        Args:
            monkeypatch: Sets HWW_GIT_COMMIT.
            tmp_path: Any folder.
        """
        monkeypatch.setenv(run_record.COMMIT_VARIABLE, "abc123")
        assert run_record.git_commit(tmp_path) == ("abc123", None)

    def test_outside_a_checkout_it_is_unknown(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Without git or a checkout, the commit is "unknown".

        Args:
            monkeypatch: Clears HWW_GIT_COMMIT.
            tmp_path: A folder outside any git checkout.
        """
        monkeypatch.delenv(run_record.COMMIT_VARIABLE, raising=False)
        assert run_record.git_commit(tmp_path) == ("unknown", None)


class TestFileFacts:
    """``file_facts``: a file's name, size, time and checksum."""

    def test_describes_without_contents(self, tmp_path: Path) -> None:
        """The facts are about the file, never what is in it.

        Args:
            tmp_path: Holds the file.
        """
        path = tmp_path / "input.xlsx"
        path.write_bytes(b"contents")
        facts = run_record.file_facts(path)
        assert facts["file"] == "input.xlsx"
        assert facts["bytes"] == 8
        assert facts["sha256"] == sha256(path)
        assert facts["modified"].endswith("+00:00")
        assert "contents" not in json.dumps(facts)
