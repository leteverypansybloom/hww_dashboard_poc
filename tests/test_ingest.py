"""Checks on reading the input files: newest survey export, clear errors.

Grouped by the function under test. Bad configs are made by changing a
copy of the frozen fixture config, so no test reads the real data.
"""

import os
import subprocess
import sys
import tomllib
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from hww_dashboard import wrangle

ConfigWriter = Callable[[wrangle.Config], Path]


def to_toml(cfg: wrangle.Config) -> str:
    """Write a config dict back as TOML.

    Handles only what config.toml uses: sections of strings, numbers,
    booleans and lists, and arrays of tables such as [[was.sessions]].

    Args:
        cfg: The config, as from ``tomllib.load``.

    Returns:
        The TOML text.
    """

    def value(v: object) -> str:
        """Format one TOML value.

        Args:
            v: The value.

        Returns:
            The value as TOML.
        """
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, str):
            return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
        if isinstance(v, list):
            return "[" + ", ".join(value(x) for x in v) + "]"
        return str(v)

    lines = []
    for section, settings in cfg.items():
        lines.append(f"[{section}]")
        tables = []
        for key, v in settings.items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                tables.append((key, v))
            else:
                lines.append(f"{key} = {value(v)}")
        for key, entries in tables:
            for entry in entries:
                lines.append(f"[[{section}.{key}]]")
                lines.extend(f"{k} = {value(x)}" for k, x in entry.items())
    return "\n".join(lines) + "\n"


def save_xlsx(path: Path, sheets: dict[str, list[list[object]]]) -> Path:
    """Write a small workbook.

    Args:
        path: Where to save it.
        sheets: Sheet name -> rows; the first row holds the headings.

    Returns:
        The path, for chaining.
    """
    with pd.ExcelWriter(path) as writer:
        for name, rows in sheets.items():
            pd.DataFrame(rows).to_excel(
                writer, sheet_name=name, header=False, index=False
            )
    return path


@pytest.fixture
def settings(fixture_config: Path) -> wrangle.Config:
    """A fresh copy of the frozen fixture config, safe to change.

    Returns:
        tests/data/config.toml as nested dicts.
    """
    with open(fixture_config, "rb") as f:
        return tomllib.load(f)


@pytest.fixture
def write_config(tmp_path: Path, fixture_config: Path) -> ConfigWriter:
    """Make configs in tmp_path that read the synthetic inputs.

    Returns:
        A function that writes a config dict to tmp_path/config.toml and
        returns its path. It first points the dict's [paths] at the
        synthetic inputs, the live mappings and tmp_path/out.
    """
    with open(fixture_config, "rb") as f:
        paths = tomllib.load(f)["paths"]
    base = fixture_config.parent

    def write(cfg: wrangle.Config) -> Path:
        """Write one config.

        Args:
            cfg: The config dict (its [paths] are changed).

        Returns:
            The config file.
        """
        cfg["paths"]["input_folder"] = str(
            (base / paths["input_folder"]).resolve()
        )
        cfg["paths"]["mappings_folder"] = str(
            (base / paths["mappings_folder"]).resolve()
        )
        cfg["paths"]["output_folder"] = str(tmp_path / "out")
        path = tmp_path / "config.toml"
        path.write_text(to_toml(cfg), encoding="utf-8")
        return path

    return write


class TestNewestMatch:
    """``newest_match``: pick the latest survey export in a folder."""

    def test_uses_the_date_in_the_name(self, tmp_path: Path) -> None:
        """The latest YYYY-MM-DD in the name wins, whatever the save order."""
        for day in ("2026-09-23", "2026-10-01", "2025-12-31"):
            name = f"hww-employer-survey-tool-{day}.xlsx"
            (tmp_path / name).write_bytes(b"")
        lock_file = "~$hww-employer-survey-tool-2027-01-01.xlsx"
        (tmp_path / lock_file).write_bytes(b"")  # Excel's lock file
        (tmp_path / "other.xlsx").write_bytes(b"")
        chosen = wrangle.newest_match(
            tmp_path, "*employer-survey-tool-*.xlsx", "Survey"
        )
        assert chosen.name == "hww-employer-survey-tool-2026-10-01.xlsx"

    def test_breaks_ties_by_save_time(self, tmp_path: Path) -> None:
        """Two exports from the same day: the one saved last wins."""
        first = tmp_path / "survey-2026-10-01.xlsx"
        second = tmp_path / "survey-2026-10-01 (1).xlsx"
        for path, saved in ((first, 2_000_000_000), (second, 1_000_000_000)):
            path.write_bytes(b"")
            os.utime(path, (saved, saved))
        chosen = wrangle.newest_match(tmp_path, "survey-*.xlsx", "Survey")
        assert chosen == first

    def test_no_match_names_the_pattern(self, tmp_path: Path) -> None:
        """The message gives the pattern and the Excel files that exist."""
        (tmp_path / "something else.xlsx").write_bytes(b"")
        with pytest.raises(
            wrangle.InputError,
            match=r"no file matching '\*survey\*.xlsx'.*something",
        ):
            wrangle.newest_match(tmp_path, "*survey*.xlsx", "Survey")


class TestShippedConfig:
    """The project's own config.toml, the one ``python wrangle.py`` uses."""

    @pytest.fixture
    def shipped(self, project_folder: Path) -> wrangle.Config:
        """The shipped config, which points at the real inputs.

        Returns:
            config.toml as nested dicts. No input file is read.
        """
        with open(project_folder / "config.toml", "rb") as f:
            return tomllib.load(f)

    def test_passes_the_checks(self, shipped: wrangle.Config) -> None:
        """Every required setting is there, with a valid value."""
        wrangle.check_config(shipped)

    def test_finds_the_survey_by_pattern(
        self, shipped: wrangle.Config
    ) -> None:
        """A new survey download needs no config change."""
        assert "file_pattern" in shipped["survey"]


class TestInputFile:
    """``input_file``: find one source's spreadsheet."""

    def test_missing_file_is_reported_with_a_suggestion(
        self, tmp_path: Path
    ) -> None:
        """A misspelt file name points at the closest file in the folder."""
        (tmp_path / "dummy_was_database.xlsx").write_bytes(b"")
        with pytest.raises(
            wrangle.InputError,
            match=r"file not found.*Did you mean 'dummy_was_database",
        ):
            wrangle.input_file(
                tmp_path, {"file": "dummy_was_databse.xlsx"}, "WAS database"
            )


class TestReadSheet:
    """``read_sheet``: read one sheet, with clear errors for bad files."""

    def test_missing_sheet_lists_the_sheets(self, tmp_path: Path) -> None:
        """A wrong sheet name or number names the sheets there are."""
        path = save_xlsx(
            tmp_path / "signups.xlsx", {"Account signups": [["Org"], ["A"]]}
        )
        with pytest.raises(
            wrangle.InputError,
            match=r"no sheet 'Account signup'.*Did you mean",
        ):
            wrangle.read_sheet(path, "Account signup", 1)
        with pytest.raises(wrangle.InputError, match=r"no sheet number 3"):
            wrangle.read_sheet(path, 3, 1)

    def test_missing_column_is_caught_as_the_file_is_read(
        self, tmp_path: Path
    ) -> None:
        """Missing headings are reported with file, sheet and heading row."""
        path = save_xlsx(
            tmp_path / "was.xlsx",
            {"query": [["Title", "Sector"], ["Org 1", "Public"]]},
        )
        with pytest.raises(
            wrangle.InputError,
            match=(
                r"was.xlsx, sheet 'query'.*\['Sectr'\]. "
                r"Did you mean 'Sector'"
            ),
        ):
            wrangle.read_sheet(path, 0, 1, "WAS", ["Title", "Sectr"])
        df = wrangle.read_sheet(path, 0, 1, "WAS", ["Title", "Sector"])
        assert list(df.columns) == ["Title", "Sector", "excel_row"]

    def test_header_row_past_the_end_of_the_sheet(
        self, tmp_path: Path
    ) -> None:
        """A header_row beyond the data says how many rows the sheet has."""
        path = save_xlsx(tmp_path / "small.xlsx", {"Sheet1": [["Org"], ["A"]]})
        with pytest.raises(
            wrangle.InputError, match=r"header_row is 5 .* only 2 row"
        ):
            wrangle.read_sheet(path, 0, 5)

    def test_file_that_is_not_excel(self, tmp_path: Path) -> None:
        """A file with the wrong content gets a plain message."""
        path = tmp_path / "broken.xlsx"
        path.write_text("not a workbook", encoding="utf-8")
        with pytest.raises(
            wrangle.InputError, match="not a readable .xlsx file"
        ):
            wrangle.read_sheet(path, 0, 1)


class TestLoadLookup:
    """``load_lookup``: read a raw_value -> agreed_value mapping."""

    def test_mapping_file_missing_a_column(self, tmp_path: Path) -> None:
        """Mapping CSVs are checked for their headings too."""
        path = tmp_path / "sector.csv"
        path.write_text("raw,agreed_value\nPublic,Public\n", encoding="utf-8")
        with pytest.raises(
            wrangle.InputError, match=r"mappings/sector.csv.*\['raw_value'\]"
        ):
            wrangle.load_lookup(path)


class TestCheckConfig:
    """``check_config``: bad settings stop before any file is read."""

    @pytest.mark.parametrize(
        ("change", "message"),
        [
            (
                lambda c: c["was"].pop("org"),
                r"\[was\] is missing setting\(s\) \['org'\]",
            ),
            (lambda c: c.pop("peer"), r"section \[peer\] is missing"),
            (
                lambda c: c["was"].update(completed_rule="whenever"),
                "completed_rule 'whenever'",
            ),
            (
                lambda c: c["employers"].update(source_priority=["was"]),
                "source_priority",
            ),
            (
                lambda c: [
                    c["survey"].pop(k, None) for k in ("file", "file_pattern")
                ],
                r"\[survey\] needs 'file' or 'file_pattern'",
            ),
        ],
    )
    def test_problem_is_named(
        self,
        settings: wrangle.Config,
        change: Callable[[wrangle.Config], object],
        message: str,
    ) -> None:
        """Each bad config gives a message naming the section and setting.

        Args:
            settings: A copy of the fixture config.
            change: Breaks the config in one way.
            message: A pattern the error message must match.
        """
        change(settings)
        with pytest.raises(wrangle.InputError, match=message):
            wrangle.check_config(settings)

    @pytest.mark.parametrize(
        ("section", "key", "value"),
        [
            ("survey", "keep_other_free_text", "false"),
            ("survey", "sheet", True),
            ("survey", "header_row", 0),
            ("survey", "header_row", True),
            ("paths", "input_folder", 4),
            ("was", "topic_separator", ""),
            ("was", "sessions", [1]),
            ("was", "sessions", [{"number": 1, "date": "D"}] * 2),
            ("employers", "source_priority", [1, "peer", "was", "survey"]),
        ],
    )
    def test_rejects_wrong_types(
        self, settings: wrangle.Config, section: str, key: str, value: object
    ) -> None:
        """Reject malformed settings before reading workbooks.

        Args:
            settings: Fresh fixture configuration.
            section: Section to damage.
            key: Setting to damage.
            value: Invalid TOML value or shape.
        """
        settings[section][key] = value
        with pytest.raises(wrangle.InputError, match="config.toml"):
            wrangle.check_config(settings)


class TestMain:
    """``main``: the command line, ``python wrangle.py [config.toml]``."""

    def test_input_problem_exits_with_1_and_a_message(
        self,
        settings: wrangle.Config,
        write_config: ConfigWriter,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A bad survey pattern: no traceback, exit 1, nothing written."""
        settings["survey"]["file_pattern"] = "no-such-export-*.xlsx"
        code = wrangle.main([str(write_config(settings))])
        assert code == 1
        assert (
            "Stopped: Survey export: no file matching 'no-such-export-*.xlsx'"
            in caplog.text
        )
        assert not list((tmp_path / "out").glob("*.csv"))


class TestWriteConfig:
    """The ``write_config`` fixture that the tests above rely on."""

    def test_unchanged_copy_runs(
        self,
        settings: wrangle.Config,
        write_config: ConfigWriter,
        run_time: datetime,
    ) -> None:
        """An unchanged copy of the fixture config runs normally."""
        tables = wrangle.run(write_config(settings), now=run_time)
        assert len(tables["dim_employer"]) > 0


class TestLauncher:
    """``python wrangle.py [config.toml]``: the launcher script."""

    def test_runs_the_pipeline_with_a_config_argument(
        self,
        project_folder: Path,
        settings: wrangle.Config,
        write_config: ConfigWriter,
        tmp_path: Path,
    ) -> None:
        """The script runs in its own process and writes every table."""
        config = write_config(settings)
        result = subprocess.run(
            [sys.executable, str(project_folder / "wrangle.py"), str(config)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        written = {p.stem for p in (tmp_path / "out").glob("*.csv")}
        assert {"dim_employer", "fact_engagement", "dim_date"} <= written


class TestLoadMappings:
    """Reject ambiguous mappings and resolve organisation chains."""

    @pytest.mark.parametrize("rows", ["A,B\na,C\n", "A,\n", ",B\n"])
    def test_rejects_bad_lookup(self, tmp_path: Path, rows: str) -> None:
        """Fail before a conflicting or blank mapping loses data.

        Args:
            tmp_path: Temporary mapping folder.
            rows: Conflicting or incomplete CSV records.
        """
        path = tmp_path / "sector.csv"
        path.write_text("raw_value,agreed_value\n" + rows, encoding="utf-8")
        with pytest.raises(wrangle.InputError, match="sector.csv.*row"):
            wrangle.load_lookup(path)

    @pytest.mark.parametrize("cycle", [False, True])
    def test_override_chains(
        self, tmp_path: Path, project_folder: Path, cycle: bool
    ) -> None:
        """Resolve chains to one employer or reject a cycle.

        Args:
            tmp_path: Temporary mapping folder.
            project_folder: Repository containing the non-personal mappings.
            cycle: Whether the last override closes a cycle.
        """
        import shutil

        shutil.copytree(project_folder / "mappings", tmp_path / "maps")
        maps = tmp_path / "maps"
        tail = "C,A\n" if cycle else "C,C\n"
        (maps / "org_overrides.csv").write_text(
            "raw_name,canonical_name\nA,B\nB,C\n" + tail,
            encoding="utf-8",
        )
        if cycle:
            with pytest.raises(wrangle.InputError, match="org_overrides.csv"):
                wrangle.load_mappings(maps)
        else:
            _, overrides = wrangle.load_mappings(maps)
            assert overrides == {"a": "C", "b": "C", "c": "C"}
