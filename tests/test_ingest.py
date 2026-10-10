"""Checks on reading the input files: newest survey export and clear errors."""

import os
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import wrangle

CONFIG = ROOT / "config.toml"


def real_config() -> wrangle.Config:
    """Return the project's config.toml as a dict."""
    with open(CONFIG, "rb") as f:
        return tomllib.load(f)


def to_toml(cfg: wrangle.Config) -> str:
    """Write a config dict back as TOML (enough for the settings used here)."""

    def value(v: object) -> str:
        """Format one TOML value."""
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


def config_in(tmp_path: Path, cfg: wrangle.Config) -> Path:
    """Write a config to tmp_path that reads the real inputs and mappings."""
    cfg["paths"]["input_folder"] = str((ROOT / real_config()["paths"]["input_folder"]).resolve())
    cfg["paths"]["mappings_folder"] = str(ROOT / "mappings")
    cfg["paths"]["output_folder"] = str(tmp_path / "out")
    path = tmp_path / "config.toml"
    path.write_text(to_toml(cfg), encoding="utf-8")
    return path


def save_xlsx(path: Path, sheets: dict[str, list[list[object]]]) -> Path:
    """Write a small workbook: sheet name -> rows (the first row holds the headings)."""
    with pd.ExcelWriter(path) as writer:
        for name, rows in sheets.items():
            pd.DataFrame(rows).to_excel(writer, sheet_name=name, header=False, index=False)
    return path


# ---------------------------------------------------------------- newest survey export


def test_newest_match_uses_the_date_in_the_name(tmp_path: Path) -> None:
    """The latest YYYY-MM-DD in the name wins, whatever order the files were saved in."""
    for day in ("2026-09-23", "2026-10-01", "2025-12-31"):
        (tmp_path / f"hww-employer-survey-tool-{day}.xlsx").write_bytes(b"")
    (tmp_path / "~$hww-employer-survey-tool-2027-01-01.xlsx").write_bytes(b"")  # Excel lock file
    (tmp_path / "other.xlsx").write_bytes(b"")
    chosen = wrangle.newest_match(tmp_path, "*employer-survey-tool-*.xlsx", "Survey")
    assert chosen.name == "hww-employer-survey-tool-2026-10-01.xlsx"


def test_newest_match_breaks_ties_by_save_time(tmp_path: Path) -> None:
    """Two exports from the same day: the one saved last wins."""
    first = tmp_path / "survey-2026-10-01.xlsx"
    second = tmp_path / "survey-2026-10-01 (1).xlsx"
    for path, saved in ((first, 2_000_000_000), (second, 1_000_000_000)):
        path.write_bytes(b"")
        os.utime(path, (saved, saved))
    assert wrangle.newest_match(tmp_path, "survey-*.xlsx", "Survey") == first


def test_newest_match_with_no_file_names_the_pattern(tmp_path: Path) -> None:
    """No match: the message gives the pattern and the Excel files that are there."""
    (tmp_path / "something else.xlsx").write_bytes(b"")
    with pytest.raises(wrangle.InputError, match=r"no file matching '\*survey\*.xlsx'.*something"):
        wrangle.newest_match(tmp_path, "*survey*.xlsx", "Survey")


def test_config_uses_a_pattern_for_the_survey() -> None:
    """The survey export is found by pattern, so a new download needs no config change."""
    assert "file_pattern" in real_config()["survey"]


# ---------------------------------------------------------------- clear errors


def test_missing_file_is_reported_with_a_suggestion(tmp_path: Path) -> None:
    """A misspelt file name points at the closest file in the folder."""
    (tmp_path / "dummy_was_database.xlsx").write_bytes(b"")
    with pytest.raises(
        wrangle.InputError, match=r"file not found.*Did you mean 'dummy_was_database"
    ):
        wrangle.input_file(tmp_path, {"file": "dummy_was_databse.xlsx"}, "WAS database")


def test_missing_sheet_lists_the_sheets(tmp_path: Path) -> None:
    """A wrong sheet name lists the real sheets and suggests the closest."""
    path = save_xlsx(tmp_path / "signups.xlsx", {"Account signups": [["Org"], ["A"]]})
    with pytest.raises(wrangle.InputError, match=r"no sheet 'Account signup'.*Did you mean"):
        wrangle.read_sheet(path, "Account signup", 1)
    with pytest.raises(wrangle.InputError, match=r"no sheet number 3"):
        wrangle.read_sheet(path, 3, 1)


def test_missing_column_is_caught_as_the_file_is_read(tmp_path: Path) -> None:
    """Missing headings are reported with the file, sheet and heading row."""
    path = save_xlsx(tmp_path / "was.xlsx", {"query": [["Title", "Sector"], ["Org 1", "Public"]]})
    with pytest.raises(
        wrangle.InputError, match=r"was.xlsx, sheet 'query'.*\['Sectr'\]. Did you mean 'Sector'"
    ):
        wrangle.read_sheet(path, 0, 1, "WAS", ["Title", "Sectr"])
    df = wrangle.read_sheet(path, 0, 1, "WAS", ["Title", "Sector"])
    assert list(df.columns) == ["Title", "Sector", "excel_row"]


def test_header_row_past_the_end_of_the_sheet(tmp_path: Path) -> None:
    """A header_row beyond the data says how many rows the sheet has."""
    path = save_xlsx(tmp_path / "small.xlsx", {"Sheet1": [["Org"], ["A"]]})
    with pytest.raises(wrangle.InputError, match=r"header_row is 5 .* only 2 row"):
        wrangle.read_sheet(path, 0, 5)


def test_file_that_is_not_excel(tmp_path: Path) -> None:
    """A file with the wrong content gets a plain message, not a zipfile traceback."""
    path = tmp_path / "broken.xlsx"
    path.write_text("not a workbook", encoding="utf-8")
    with pytest.raises(wrangle.InputError, match="not a readable .xlsx file"):
        wrangle.read_sheet(path, 0, 1)


def test_mapping_file_missing_a_column(tmp_path: Path) -> None:
    """Mapping CSVs are checked for their headings too."""
    path = tmp_path / "sector.csv"
    path.write_text("raw,agreed_value\nPublic,Public\n", encoding="utf-8")
    with pytest.raises(wrangle.InputError, match=r"mappings/sector.csv.*\['raw_value'\]"):
        wrangle.load_lookup(path)


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda c: c["was"].pop("org"), r"\[was\] is missing setting\(s\) \['org'\]"),
        (lambda c: c.pop("peer"), r"section \[peer\] is missing"),
        (lambda c: c["was"].update(completed_rule="whenever"), "completed_rule 'whenever'"),
        (lambda c: c["employers"].update(source_priority=["was"]), "source_priority"),
        (lambda c: c["survey"].pop("file_pattern"), r"\[survey\] needs 'file' or 'file_pattern'"),
    ],
)
def test_config_problems_stop_before_any_file_is_read(
    change: Callable[[wrangle.Config], object], message: str
) -> None:
    """Each bad config gives a message naming the section and setting."""
    cfg = real_config()
    change(cfg)
    with pytest.raises(wrangle.InputError, match=message):
        wrangle.check_config(cfg)


def test_command_line_exits_with_1_and_a_message(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Command line with a bad survey pattern: no traceback, exit code 1, nothing written."""
    cfg = real_config()
    cfg["survey"]["file_pattern"] = "no-such-export-*.xlsx"
    code = wrangle.main([str(config_in(tmp_path, cfg))])
    assert code == 1
    assert "Stopped: Survey export: no file matching 'no-such-export-*.xlsx'" in caplog.text
    assert not list((tmp_path / "out").glob("*.csv"))


def test_config_written_by_these_tests_runs(tmp_path: Path) -> None:
    """Sanity check for the helpers above: an unchanged copy of the config runs normally."""
    tables = wrangle.run(config_in(tmp_path, real_config()))
    assert len(tables["dim_employer"]) > 0
