"""Checks on reading the input files: newest survey export, clear errors.

Grouped by the function under test. Bad configs are made by changing a
copy of the frozen fixture config, so no test reads the real data.
"""

import json
import os
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Callable, Sequence
from datetime import date, datetime
from functools import partial
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


def header_only_config(
    tmp_path: Path,
    fixture_config: Path,
    settings: wrangle.Config,
    write_config: ConfigWriter,
    empty: Sequence[str],
) -> Path:
    """Write a config whose inputs keep only their headings for some sources.

    Args:
        tmp_path: Holds the copied workbooks.
        fixture_config: The frozen config, whose inputs are copied.
        settings: The config dict to point at the copies (changed).
        write_config: Writes the config.
        empty: The sources whose sheets lose every row below the headings.

    Returns:
        The config file.
    """
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    original = fixture_config.parent / "inputs"
    for source in wrangle.SOURCES:
        cfg = settings[source]
        path = wrangle.input_file(original, cfg, source)
        if source not in empty:
            shutil.copy(path, inputs / path.name)
            continue
        with pd.ExcelFile(path) as book:
            sheet = cfg["sheet"]
            name = book.sheet_names[sheet] if isinstance(sheet, int) else sheet
            raw = book.parse(sheet_name=sheet, header=None, dtype=object)
        save_xlsx(
            inputs / path.name,
            {str(name): raw.head(cfg["header_row"]).values.tolist()},
        )
    config = write_config(settings)
    settings["paths"]["input_folder"] = inputs.as_posix()
    config.write_text(to_toml(settings), encoding="utf-8")
    return config


@pytest.fixture
def settings(fixture_config: Path) -> wrangle.Config:
    """A fresh copy of the frozen fixture config, safe to change.

    Args:
        fixture_config: Frozen configuration pointing only to synthetic inputs.

    Returns:
        tests/data/config.toml as nested dicts.
    """
    with open(fixture_config, "rb") as f:
        return tomllib.load(f)


@pytest.fixture
def write_config(tmp_path: Path, fixture_config: Path) -> ConfigWriter:
    """Make configs in tmp_path that read the synthetic inputs.

    Args:
        tmp_path: Isolated folder for generated test inputs and outputs.
        fixture_config: Frozen configuration pointing only to synthetic inputs.

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

    def test_equal_timestamps_use_filename(self, tmp_path: Path) -> None:
        """Resolve full timestamp ties without filesystem iteration order."""
        paths = [tmp_path / f"survey-2026-10-01-{c}.xlsx" for c in "az"]
        for path in paths:
            path.write_bytes(b"")
            os.utime(path, (2_000_000_000, 2_000_000_000))
        assert wrangle.newest_match(tmp_path, "*.xlsx", "Survey") == paths[1]


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

    def test_blank_duplicate_headers_and_empty_body(
        self, tmp_path: Path
    ) -> None:
        """Header-only exports keep unique names and row metadata."""
        path = save_xlsx(
            tmp_path / "empty.xlsx", {"Sheet1": [["Org", None, "Org"]]}
        )
        table = wrangle.read_sheet(path, 0, 1)
        assert table.empty
        assert list(table.columns) == ["Org", "B", "Org.1", "excel_row"]


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
            (
                lambda c: c.update(output={"target": "cloud"}),
                r"\[output\] target must be one of",
            ),
            (
                lambda c: c.update(
                    output={"target": "bigquery", "project": "p"}
                ),
                r"\[output\] dataset must be nonblank",
            ),
            (
                lambda c: c.update(output={"location": ""}),
                r"\[output\] location must be nonblank",
            ),
            (
                lambda c: c["paths"].update(log_folder=" "),
                r"\[paths\] log_folder must be nonblank",
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

    def test_rejects_personal_source_column(
        self, settings: wrangle.Config
    ) -> None:
        """A personal name cannot be configured as the employer name."""
        settings["signups"]["org"] = "Full Name"
        with pytest.raises(wrangle.InputError, match="personal"):
            wrangle.check_config(settings)

    @pytest.fixture
    def shipped(self, project_folder: Path) -> wrangle.Config:
        """The shipped config, which points at the real inputs.

        Args:
            project_folder: Repository holding launchers and mappings.

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

    def test_matches_the_frozen_test_config(
        self, shipped: wrangle.Config, settings: wrangle.Config
    ) -> None:
        """The tests run with the shipped settings, not a drifted copy.

        Only where things are may differ: the folders, the output target
        and the file names.

        Args:
            shipped: config.toml.
            settings: The frozen test config.
        """

        def rules(cfg: wrangle.Config) -> wrangle.Config:
            """Keep everything except where things are.

            Args:
                cfg: A config.

            Returns:
                The config without [paths], [output], [landed] and file
                names.
            """
            kept = {
                section: dict(values)
                for section, values in cfg.items()
                if section not in ("paths", "output", "landed")
            }
            for values in kept.values():
                for key in ("file", "file_pattern"):
                    values.pop(key, None)
            return kept

        assert rules(shipped) == rules(settings)


class TestMain:
    """``main``: the command line, ``python wrangle.py [config.toml]``."""

    def test_input_problem_exits_with_1_and_a_message(
        self,
        settings: wrangle.Config,
        write_config: ConfigWriter,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        run_time: datetime,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A bad survey pattern: no traceback, exit 1, nothing written."""
        monkeypatch.setattr(wrangle, "run", partial(wrangle.run, now=run_time))
        settings["survey"]["file_pattern"] = "no-such-export-*.xlsx"
        code = wrangle.main([str(write_config(settings))])
        assert code == 1
        assert (
            "Stopped: Survey export: no file matching 'no-such-export-*.xlsx'"
            in caplog.text
        )
        assert not list((tmp_path / "out").glob("*.csv"))

    def test_output_problem_exits_with_1_and_what_to_do(
        self,
        settings: wrangle.Config,
        write_config: ConfigWriter,
        caplog: pytest.LogCaptureFixture,
        run_time: datetime,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An output file held open (as Excel does): exit 1, no traceback.

        Args:
            settings: A copy of the fixture config.
            write_config: Writes a config that reads the synthetic inputs.
            caplog: Captures the log.
            run_time: The tests' fixed run time.
            monkeypatch: Replaces the output writer.
        """

        def locked(*args: object, **kwargs: object) -> list[tuple[str, int]]:
            """Fail the way Windows does when a file is open elsewhere.

            Args:
                *args: Ignored.
                **kwargs: Ignored.

            Raises:
                PermissionError: Always.
            """
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(wrangle, "run", partial(wrangle.run, now=run_time))
        monkeypatch.setattr(wrangle, "write_outputs", locked)
        code = wrangle.main([str(write_config(settings))])
        assert code == 1
        assert "Could not write the outputs" in caplog.text
        assert "Close any output file" in caplog.text
        assert "Traceback" not in caplog.text

    def test_unexpected_error_exits_with_2(
        self,
        settings: wrangle.Config,
        write_config: ConfigWriter,
        caplog: pytest.LogCaptureFixture,
        capsys: pytest.CaptureFixture[str],
        run_time: datetime,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """A bug: exit 2, its line on the console, details in the log.

        Args:
            settings: A copy of the fixture config.
            write_config: Writes a config that reads the synthetic inputs.
            caplog: Captures the log records.
            capsys: Captures the console.
            run_time: The tests' fixed run time.
            monkeypatch: Breaks one step of the pipeline.
            tmp_path: Holds the config, so the log folder too.
        """

        def broken(*args: object, **kwargs: object) -> None:
            """Fail as a bug would.

            Args:
                *args: Ignored.
                **kwargs: Ignored.

            Raises:
                KeyError: Always.
            """
            raise KeyError("employer_id")

        monkeypatch.setattr(wrangle, "run", partial(wrangle.run, now=run_time))
        monkeypatch.setattr(wrangle, "reconcile", broken)
        monkeypatch.delenv("HWW_LOG_FORMAT", raising=False)
        code = wrangle.main([str(write_config(settings))])
        assert code == 2
        assert "Unexpected error (KeyError at wrangle.py:" in caplog.text
        assert "Traceback" not in capsys.readouterr().err
        [log_file] = (tmp_path / "logs").glob("*.log")
        assert "Traceback" in log_file.read_text("utf-8")

    def test_saves_a_log_of_each_run(
        self,
        settings: wrangle.Config,
        write_config: ConfigWriter,
        run_time: datetime,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """A run's log is kept in logs/ next to the config.

        Args:
            settings: A copy of the fixture config.
            write_config: Writes a config that reads the synthetic inputs.
            run_time: The tests' fixed run time.
            monkeypatch: Fixes the clock and the log format.
            tmp_path: Holds the config, so the log folder too.
        """
        monkeypatch.setattr(wrangle, "run", partial(wrangle.run, now=run_time))
        monkeypatch.delenv("HWW_LOG_FORMAT", raising=False)
        assert wrangle.main([str(write_config(settings))]) == 0
        [log_file] = (tmp_path / "logs").glob("*.log")
        text = log_file.read_text("utf-8")
        assert f"Run {log_file.stem}" in text
        assert "Wrote 11 tables" in text
        assert "Report needs attention: 1 value(s) not in the" in text

    def test_json_mode_logs_lines_of_json_and_no_file(
        self,
        settings: wrangle.Config,
        write_config: ConfigWriter,
        capsys: pytest.CaptureFixture[str],
        run_time: datetime,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """With HWW_LOG_FORMAT=json each console line is a JSON object.

        Args:
            settings: A copy of the fixture config.
            write_config: Writes a config that reads the synthetic inputs.
            capsys: Captures the console.
            run_time: The tests' fixed run time.
            monkeypatch: Fixes the clock and the log format.
            tmp_path: Holds the config, so the log folder too.
        """
        monkeypatch.setattr(wrangle, "run", partial(wrangle.run, now=run_time))
        monkeypatch.setenv("HWW_LOG_FORMAT", "json")
        assert wrangle.main([str(write_config(settings))]) == 0
        lines = capsys.readouterr().err.strip().splitlines()
        entries = [json.loads(line) for line in lines]
        assert {e["severity"] for e in entries} >= {"INFO", "WARNING"}
        assert len({e["run_id"] for e in entries}) == 1
        assert not (tmp_path / "logs").exists()

    def test_unknown_log_format_stops_at_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An invalid HWW_LOG_FORMAT is an input problem: exit 1.

        Args:
            monkeypatch: Sets the log format.
        """
        monkeypatch.setenv("HWW_LOG_FORMAT", "xml")
        assert wrangle.main(["no-config.toml"]) == 1


class TestErrorLocation:
    """``error_location``: where an unexpected error was raised."""

    def test_names_the_innermost_package_line(self) -> None:
        """The last frame inside hww_dashboard is named, file and line."""
        with pytest.raises(wrangle.InputError) as caught:
            wrangle.check_config({})
        assert wrangle.error_location(caught.value).startswith("wrangle.py:")

    def test_error_without_a_traceback(self) -> None:
        """An error that was never raised has no location."""
        assert wrangle.error_location(KeyError("x")) == "unknown"


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
        run_time: datetime,
    ) -> None:
        """The script runs in its own process and writes every table."""
        config = write_config(settings)
        harness = (
            "from datetime import datetime; from functools import partial; "
            "import runpy, sys; from hww_dashboard import wrangle; "
            "stamp = datetime.fromisoformat(sys.argv.pop()); "
            "wrangle.run = partial(wrangle.run, now=stamp); "
            "sys.argv[0] = sys.argv.pop(1); "
            "runpy.run_path(sys.argv[0], run_name='__main__')"
        )
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                harness,
                str(project_folder / "wrangle.py"),
                str(config),
                run_time.isoformat(),
            ],
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


class TestReadCsvText:
    """Mapping input errors identify the file and required repair."""

    @pytest.mark.parametrize(
        "content", [b"", b"a,b\n1,2\n3,4,5\n", b"a\n\xff"]
    )
    def test_unreadable_csv(self, tmp_path: Path, content: bytes) -> None:
        """Translate CSV format and encoding errors to InputError.

        Args:
            tmp_path: Temporary mapping folder.
            content: Empty, malformed or non-UTF-8 file bytes.
        """
        path = tmp_path / "sector.csv"
        path.write_bytes(content)
        with pytest.raises(wrangle.InputError, match="sector.csv.*UTF-8"):
            wrangle.read_csv_text(path)

    def test_bom_and_literal_null_strings(self, tmp_path: Path) -> None:
        """A BOM is ignored while NA and None remain literal text."""
        path = tmp_path / "map.csv"
        path.write_text(
            "raw_value,agreed_value\nNA,None\n", encoding="utf-8-sig"
        )
        table = wrangle.read_csv_text(path, ["raw_value", "agreed_value"])
        assert table.iloc[0].tolist() == ["NA", "None"]


class TestLoadWas:
    """WAS request identifiers must be unique before session expansion."""

    def test_rejects_duplicate_ids(
        self, tmp_path: Path, settings: wrangle.Config
    ) -> None:
        """Duplicate requests cannot produce duplicate session/event keys."""
        cfg = settings["was"].copy()
        cfg.update(file="was.xlsx", sheet=0, header_row=1, sessions=[])
        keys = [
            "id",
            "org",
            "enquiry_date",
            "fallback_enquiry_date",
            "size",
            "sector",
            "industry",
            "sites",
        ]
        rows: list[list[object]] = [[cfg[k] for k in keys]]
        rows.extend([[1, "Org A", "", "", "", "", "", ""]] * 2)
        save_xlsx(tmp_path / "was.xlsx", {"Sheet1": rows})
        with pytest.raises(wrangle.InputError, match="was.xlsx.*duplicate"):
            wrangle.load_was(
                cfg,
                wrangle.FolderInputs(tmp_path),
                {n: {} for n in wrangle.LOOKUP_NAMES},
                {},
                wrangle.Report(),
            )


class TestLoadPeer:
    """Peer identifiers must be unique before engagement expansion."""

    def test_rejects_duplicate_ids(
        self, tmp_path: Path, settings: wrangle.Config
    ) -> None:
        """Repeated source keys cannot silently double engagement counts."""
        cfg = settings["peer"].copy()
        cfg.update(file="peer.xlsx", sheet=0, header_row=1)
        keys = ["id", "org", "interest_date", "size", "sector", "industry"]
        rows: list[list[object]] = [[cfg[k] for k in keys]]
        rows.extend([[1, "Org A", "", "", "", ""]] * 2)
        save_xlsx(tmp_path / "peer.xlsx", {"Sheet1": rows})
        with pytest.raises(wrangle.InputError, match="peer.xlsx.*duplicate"):
            wrangle.load_peer(
                cfg,
                wrangle.FolderInputs(tmp_path),
                {n: {} for n in wrangle.LOOKUP_NAMES},
                {},
                wrangle.Report(),
            )


class TestLoadSurvey:
    """Survey translations must not silently overwrite a competing target."""

    def test_rejects_conflicting_translations(
        self,
        tmp_path: Path,
        project_folder: Path,
        fixture_config: Path,
        settings: wrangle.Config,
    ) -> None:
        """Case-equivalent translation keys cannot disagree."""
        maps = tmp_path / "maps"
        shutil.copytree(project_folder / "mappings", maps)
        (maps / "survey_answer_translations.csv").write_text(
            "question_id,raw_answer,answer\nQ01,Raw,A\nQ01,RAW,B\n",
            encoding="utf-8",
        )
        lookups, overrides = wrangle.load_mappings(maps)
        with pytest.raises(
            wrangle.InputError, match="survey_answer_translations.csv"
        ):
            wrangle.load_survey(
                settings["survey"],
                wrangle.FolderInputs(fixture_config.parent / "inputs"),
                maps,
                lookups,
                overrides,
                wrangle.Report(),
            )

    def test_personal_heading_must_be_dropped(
        self, tmp_path: Path, project_folder: Path, settings: wrangle.Config
    ) -> None:
        """Reject personal survey columns before opening a workbook."""
        maps = tmp_path / "maps"
        shutil.copytree(project_folder / "mappings", maps)
        path = maps / "survey_columns.csv"
        table = wrangle.read_csv_text(path)
        table.loc[0, "column"] = "Full Name"
        table.to_csv(path, index=False)
        with pytest.raises(wrangle.InputError, match="personal columns"):
            wrangle.load_survey(
                settings["survey"],
                wrangle.FolderInputs(tmp_path),
                maps,
                {},
                {},
                wrangle.Report(),
                ["Full Name"],
            )


class TestLoadConfig:
    """Read configuration without opening any real workbooks."""

    def test_valid_fixture(self, fixture_config: Path) -> None:
        """The frozen config keeps optional free text disabled."""
        assert (
            wrangle.load_config(fixture_config)["survey"][
                "keep_other_free_text"
            ]
            is False
        )

    def test_missing_and_invalid_files(self, tmp_path: Path) -> None:
        """Missing and malformed TOML are actionable input errors."""
        path = tmp_path / "config.toml"
        with pytest.raises(wrangle.InputError, match="Config file not found"):
            wrangle.load_config(path)
        path.write_text("[broken", encoding="utf-8")
        with pytest.raises(wrangle.InputError, match="not valid TOML"):
            wrangle.load_config(path)

    def test_environment_variables_fill_placeholders(
        self,
        fixture_config: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``${NAME}`` takes the environment variable's value.

        Args:
            fixture_config: The frozen config, copied with placeholders.
            tmp_path: Holds the copy.
            monkeypatch: Sets the environment variables.
        """
        text = fixture_config.read_text("utf-8").replace(
            'input_folder = "inputs"',
            'input_folder = "${HWW_TEST_INPUTS}/${HWW_TEST_SUB}"',
        )
        path = tmp_path / "config.toml"
        path.write_text(text, encoding="utf-8")
        monkeypatch.setenv("HWW_TEST_INPUTS", "/mnt/landing")
        monkeypatch.setenv("HWW_TEST_SUB", "hww")
        cfg = wrangle.load_config(path)
        assert cfg["paths"]["input_folder"] == "/mnt/landing/hww"

    def test_unset_variables_are_named(
        self,
        fixture_config: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A placeholder with no variable stops the run, naming it.

        Args:
            fixture_config: The frozen config, copied with a placeholder.
            tmp_path: Holds the copy.
            monkeypatch: Clears the environment variable.
        """
        text = fixture_config.read_text("utf-8").replace(
            'input_folder = "inputs"', 'input_folder = "${HWW_NOT_SET}"'
        )
        path = tmp_path / "config.toml"
        path.write_text(text, encoding="utf-8")
        monkeypatch.delenv("HWW_NOT_SET", raising=False)
        with pytest.raises(wrangle.InputError, match="HWW_NOT_SET"):
            wrangle.load_config(path)


class TestInterpolate:
    """``interpolate``: placeholders in text, lists and tables."""

    def test_nested_values_and_other_types(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Text inside lists and tables is filled; numbers are left alone.

        Args:
            monkeypatch: Sets an environment variable.
        """
        monkeypatch.setenv("HWW_TEST_VALUE", "x")
        missing: set[str] = set()
        value = {"a": ["${HWW_TEST_VALUE}", 1], "b": {"c": "$NOT ${lower}"}}
        assert wrangle.interpolate(value, missing) == {
            "a": ["x", 1],
            "b": {"c": "$NOT ${lower}"},
        }
        assert missing == set()


class TestDateInName:
    """Export names use their last valid date."""

    def test_last_valid_date(self) -> None:
        """Ignore invalid calendar dates and files without a date."""
        assert wrangle.date_in_name(
            Path("2026-03-04-to-2026-04-05-2026-02-30.xlsx")
        ) == date(2026, 4, 5)
        assert wrangle.date_in_name(Path("survey.xlsx")) is None


class TestFilesIn:
    """Missing input directories provide an empty suggestion list."""

    def test_existing_and_missing_folders(self, tmp_path: Path) -> None:
        """Only direct children contribute file-name suggestions."""
        (tmp_path / "A.xlsx").write_bytes(b"")
        assert wrangle.files_in(tmp_path) == ["A.xlsx"]
        assert wrangle.files_in(tmp_path / "missing") == []


class TestRequire:
    """Missing columns name the source, location and closest spelling."""

    def test_suggests_column(self) -> None:
        """An existing column passes and a typo gives a suggestion."""
        frame = pd.DataFrame(columns=["Sector"])
        wrangle.require(frame, ["Sector"], "WAS", "book.xlsx")
        with pytest.raises(
            wrangle.InputError, match="book.xlsx.*Did you mean 'Sector'"
        ):
            wrangle.require(frame, ["Sectr"], "WAS", "book.xlsx")


class TestDropBlankRows:
    """Ignore row metadata when deciding whether an input row is blank."""

    def test_blank_cells_and_zero(self) -> None:
        """Whitespace is blank but a numeric zero is a real value."""
        frame = pd.DataFrame({"A": [None, "  ", 0], "excel_row": [2, 3, 4]})
        result = wrangle.drop_blank_rows(frame)
        assert list(result["excel_row"]) == [4]
        assert len(frame) == 3


class TestSuggest:
    """Suggest close names without inventing matches."""

    def test_close_and_unrelated_names(self) -> None:
        """A plausible typo gets a suggestion; unrelated text does not."""
        assert (
            wrangle.suggest("Sectr", ["Sector"]) == " Did you mean 'Sector'?"
        )
        assert wrangle.suggest("zzz", ["Sector"]) == ""


class TestLoadSignups:
    """Merged month cells, repeated employers and flags retain row keys."""

    def test_merged_month_and_role_cleanup(
        self, tmp_path: Path, today: date
    ) -> None:
        """A blank month inherits the previous month before rows are linked."""
        cfg: wrangle.Config = {
            "file": "signups.xlsx",
            "sheet": 0,
            "header_row": 1,
            "month": "Month",
            "org": "Org",
            "role": "Role",
            "size": "Size",
            "sector": "Sector",
            "industry": "Industry",
            "sites": "Sites",
            "completed_survey": "Survey",
            "requested_was": "WAS",
        }
        save_xlsx(
            tmp_path / "signups.xlsx",
            {
                "Sheet1": [
                    [
                        "Month",
                        "Org",
                        "Role",
                        "Size",
                        "Sector",
                        "Industry",
                        "Sites",
                        "Survey",
                        "WAS",
                    ],
                    [
                        date(2026, 1, 1),
                        "Org A",
                        "Org A",
                        "",
                        "",
                        "",
                        "",
                        "Y (Dec)",
                        "N",
                    ],
                    [None, "Org A", "Manager", "", "", "", "", "N", "Y"],
                ]
            },
        )
        report = wrangle.Report()
        frame = wrangle.load_signups(
            cfg,
            wrangle.FolderInputs(tmp_path),
            {n: {} for n in wrangle.LOOKUP_NAMES},
            {},
            report,
            today,
        )
        assert list(frame["signup_id"]) == ["SU0002", "SU0003"]
        assert list(frame["signup_month"]) == [date(2026, 1, 1)] * 2
        assert list(frame["role"]) == ["", "Manager"]
        assert list(frame["survey_dates"]) == ["2025-12-01", ""]
        assert list(frame["was_flag"]) == [False, True]

    def test_invalid_month_does_not_forward_fill(
        self, tmp_path: Path, today: date
    ) -> None:
        """A nonblank invalid month cannot inherit the previous month."""
        keys = [
            "month",
            "org",
            "role",
            "size",
            "sector",
            "industry",
            "sites",
            "completed_survey",
            "requested_was",
        ]
        cfg: wrangle.Config = {key: key for key in keys}
        cfg.update(file="signups.xlsx", sheet=0, header_row=1)
        save_xlsx(
            tmp_path / "signups.xlsx",
            {
                "Sheet1": [
                    list(keys),
                    [date(2026, 1, 1), "Org A", "", "", "", "", "", "", ""],
                    ["not a date", "Org B", "", "", "", "", "", "", ""],
                ]
            },
        )
        with pytest.raises(wrangle.InputError, match="signups.xlsx.*month"):
            wrangle.load_signups(
                cfg,
                wrangle.FolderInputs(tmp_path),
                {n: {} for n in wrangle.LOOKUP_NAMES},
                {},
                wrangle.Report(),
                today,
            )


class TestMappingPairs:
    """Two-column mappings tolerate only identical cleaned duplicates."""

    def test_identical_duplicates(self) -> None:
        """Repeated rows with the same target do not introduce ambiguity."""
        frame = pd.DataFrame({"raw": [" A ", "a"], "target": ["B", "B"]})
        assert wrangle.mapping_pairs(
            frame, "raw", "target", Path("map.csv")
        ) == {"a": "B"}


class TestRequireUniqueIds:
    """Source key checks include generated fallback identifiers."""

    def test_unique_and_duplicate_keys(self) -> None:
        """Unique identifiers pass and duplicate keys name the workbook."""
        wrangle.require_unique_ids(
            pd.DataFrame({"id": ["A", "B"]}), "id", Path("book.xlsx")
        )
        with pytest.raises(
            wrangle.InputError, match="book.xlsx.*duplicate id"
        ):
            wrangle.require_unique_ids(
                pd.DataFrame({"id": ["A", "A"]}), "id", Path("book.xlsx")
            )


class TestValidateSurveyColumns:
    """Validate answer mapping roles independently of survey data."""

    def test_duplicate_columns(self) -> None:
        """Two specifications cannot claim the same export column."""
        specs = pd.DataFrame(
            [["A", "single", "Q01", ""], ["A", "drop", "", ""]],
            columns=wrangle.MAPPING_COLUMNS["survey_columns"],
        )
        with pytest.raises(wrangle.InputError, match="unique nonblank column"):
            wrangle.validate_survey_columns(specs)


class TestCheckPublicText:
    """Contact guards inspect values without echoing them in diagnostics."""

    def test_case_insensitive_links(self) -> None:
        """Ordinary business text passes while uppercase web links fail."""
        wrangle.check_public_text("Ordinary business text", "output.csv")
        with pytest.raises(wrangle.InputError, match="output.csv"):
            wrangle.check_public_text("HTTPS://example.org", "output.csv")

    @pytest.mark.parametrize(
        "phone",
        [
            "07700 900123",
            "07700900123",
            "+44 7700 900123",
            "(029) 2018 0123",
            "0161-496-0123",
        ],
    )
    def test_uk_phone_numbers_are_caught(self, phone: str) -> None:
        """UK phone numbers stop the run, and the message omits them.

        Args:
            phone: A phone number in one of the usual layouts (all in
                Ofcom's ranges reserved for drama).
        """
        with pytest.raises(wrangle.InputError) as error:
            wrangle.check_public_text(f"call {phone} today", "notes.csv")
        assert phone not in str(error.value)

    @pytest.mark.parametrize(
        "text",
        [
            "2025-11-01;2026-08-01",
            "E0016300d,Org 1,2026-04-01",
            "PM-0011,WAS-10-S2,19460",
            "answer_order 999, fin_year 2025-26",
            "001234567890123",
        ],
    )
    def test_ordinary_numbers_pass(self, text: str) -> None:
        """Dates, ids and long reference numbers aren't phone numbers.

        Args:
            text: Text like the pipeline's own outputs.
        """
        wrangle.check_public_text(text, "output.csv")


class TestRun:
    """The pipeline handles a generation with no source records."""

    def test_header_only_sources(
        self,
        tmp_path: Path,
        fixture_config: Path,
        settings: wrangle.Config,
        write_config: ConfigWriter,
        run_time: datetime,
    ) -> None:
        """Header-only workbooks, when allowed, produce every empty table."""
        config = header_only_config(
            tmp_path, fixture_config, settings, write_config, wrangle.SOURCES
        )
        for source in wrangle.SOURCES:
            settings[source]["allow_empty"] = True
        config.write_text(to_toml(settings), encoding="utf-8")
        tables = wrangle.run(config, now=run_time)
        assert set(tables) == set(wrangle.COLUMNS) - {"survey_other_text"}
        for name, table in tables.items():
            assert list(table.columns) == wrangle.COLUMNS[name]
            if name != "question_catalogue":
                assert table.empty, name
        assert not tables["question_catalogue"].empty

    def test_an_empty_source_stops_the_run(
        self,
        tmp_path: Path,
        fixture_config: Path,
        settings: wrangle.Config,
        write_config: ConfigWriter,
        run_time: datetime,
    ) -> None:
        """An empty upload stops the run, saying how to allow it.

        Args:
            tmp_path: Holds the workbooks and config.
            fixture_config: The frozen config, whose inputs are copied.
            settings: A copy of the fixture config.
            write_config: Writes a config that reads the synthetic inputs.
            run_time: The tests' fixed run time.
        """
        config = header_only_config(
            tmp_path, fixture_config, settings, write_config, ("was",)
        )
        with pytest.raises(wrangle.InputError) as error:
            wrangle.run(config, now=run_time)
        message = str(error.value)
        assert "dummy_was_database.xlsx has no data rows" in message
        assert "allow_empty = true in [was]" in message

    def test_a_shrunken_source_needs_attention(
        self,
        tmp_path: Path,
        fixture_config: Path,
        run_time: datetime,
    ) -> None:
        """Far fewer rows than the last run is a warning, not a stop.

        Args:
            tmp_path: The output folder's parent.
            fixture_config: The frozen config.
            run_time: The tests' fixed run time.
        """
        out = tmp_path / "out"
        out.mkdir()
        previous = {
            "run_id": "earlier",
            "inputs": [{"source": "WAS database", "rows": 100}],
        }
        (out / "run_record.json").write_text(json.dumps(previous), "utf-8")
        wrangle.run(fixture_config, output_folder=out, now=run_time)
        report = (out / "data_quality_report.md").read_text("utf-8")
        assert "WAS database: 35 rows read, 65% fewer" in report
        record = json.loads((out / "run_record.json").read_text("utf-8"))
        assert record["attention"]["shrunk_sources"] == 1


class TestCheckAgreedValues:
    """``check_agreed_values``: mapping targets come from one list."""

    @pytest.fixture
    def agreed(self, tmp_path: Path) -> Path:
        """Write a short list of agreed values.

        Args:
            tmp_path: Holds the file.

        Returns:
            The agreed_values.csv path.
        """
        path = tmp_path / "agreed_values.csv"
        path.write_text(
            "dimension,agreed_value\nsector,Public\nsector,Private\n", "utf-8"
        )
        return path

    def test_targets_on_the_list_pass(self, agreed: Path) -> None:
        """Mapping to an agreed value is fine.

        Args:
            agreed: The agreed values file.
        """
        wrangle.check_agreed_values(
            {"sector": {"private sector": "Private"}}, agreed
        )

    def test_a_typo_in_a_target_is_named(self, agreed: Path) -> None:
        """A target that isn't on the list names its file and value.

        Args:
            agreed: The agreed values file.
        """
        with pytest.raises(
            wrangle.InputError, match=r"sector.csv: \['Privat'\]"
        ):
            wrangle.check_agreed_values(
                {"sector": {"private sector": "Privat"}}, agreed
            )

    @pytest.mark.parametrize("row", ["sectr,Public", "sector,", ",Public"])
    def test_bad_list_rows_are_refused(self, agreed: Path, row: str) -> None:
        """Unknown dimensions and blank values in the list stop the run.

        Args:
            agreed: The agreed values file.
            row: A bad row to add.
        """
        agreed.write_text(agreed.read_text("utf-8") + row + "\n", "utf-8")
        with pytest.raises(wrangle.InputError, match="agreed_values.csv"):
            wrangle.check_agreed_values({}, agreed)
