"""Offline probes of the HWW reference pipeline."""

import re
import shutil
import subprocess
import sys
import zipfile
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from hww_dashboard import wrangle


class TestReadSheet:
    """Workbook errors preserve privacy and reject missing formula values."""

    def test_corrupt_numeric_value_is_private(self, tmp_path: Path) -> None:
        """An unreadable cell does not disclose its text.

        Args:
            tmp_path: Synthetic workbook folder.
        """
        workbook = Workbook()
        assert isinstance(workbook.active, Worksheet)
        workbook.active.append(["value"])
        workbook.active.append([123])
        stream = BytesIO()
        workbook.save(stream)
        path = tmp_path / "synthetic.xlsx"
        marker = "synthetic.person@example.invalid"
        with zipfile.ZipFile(stream) as src:
            with zipfile.ZipFile(path, "w") as dst:
                for name in src.namelist():
                    value = src.read(name)
                    if name == "xl/worksheets/sheet1.xml":
                        value = value.replace(
                            b"<v>123</v>", f"<v>{marker}</v>".encode()
                        )
                    dst.writestr(name, value)
        with pytest.raises(wrangle.InputError) as caught:
            wrangle.read_sheet(path, 0, 1)
        assert marker not in str(caught.value), str(caught.value)

    def test_uncached_formula_is_rejected(self, tmp_path: Path) -> None:
        """An unsaved formula cannot silently become a missing date.

        Args:
            tmp_path: Synthetic workbook folder.
        """
        workbook = Workbook()
        assert isinstance(workbook.active, Worksheet)
        workbook.active.append(["id", "session_date"])
        workbook.active.append(["1", "=DATE(2026,1,1)"])
        path = tmp_path / "formula.xlsx"
        workbook.save(path)
        with pytest.raises(wrangle.InputError):
            frame = wrangle.read_sheet(path, 0, 1)
            print(frame.to_dict(orient="records"))


class TestBuildDimEmployer:
    """Input order does not decide a tied display spelling."""

    def test_spelling_tie_is_stable(self) -> None:
        """Equivalent organisations retain the same displayed name."""
        rows = pd.DataFrame(
            {
                "org": ["ACME", "Acme"],
                "sector": ["Unknown"] * 2,
                "industry": ["Unknown"] * 2,
                "size_band": ["Unknown"] * 2,
                "sites_band": ["Unknown"] * 2,
                "source": ["signups"] * 2,
                "position": [0, 1],
            }
        )
        priority = ["signups", "survey", "was", "peer"]
        left = wrangle.build_dim_employer(rows, priority, wrangle.Report())
        right = wrangle.build_dim_employer(
            rows.iloc[::-1], priority, wrangle.Report()
        )
        assert wrangle.csv_text(left, "dim_employer") == wrangle.csv_text(
            right, "dim_employer"
        )


class TestRun:
    """Unreadable formulas cannot silently change published dates."""

    def test_session_formula_does_not_lose_date(self, tmp_path: Path) -> None:
        """A full synthetic run preserves dates or refuses the workbook.

        Args:
            tmp_path: Synthetic input and output folders.
        """
        project = Path(__file__).resolve().parent.parent
        inputs = tmp_path / "inputs"
        shutil.copytree(project / "tests/data/inputs", inputs)
        config = (project / "tests/data/config.toml").read_text()
        config = config.replace(
            'input_folder = "inputs"', f'input_folder = "{inputs.as_posix()}"'
        )
        mappings = (project / "mappings").resolve().as_posix()
        config = config.replace(
            'mappings_folder = "../../mappings"',
            f'mappings_folder = "{mappings}"',
        )
        path = tmp_path / "config.toml"
        path.write_text(config)
        before = wrangle.run(path, tmp_path / "before", datetime(2026, 10, 10))
        workbook_path = inputs / "dummy_was_database.xlsx"
        workbook = load_workbook(workbook_path)
        sheet = workbook.active
        assert isinstance(sheet, Worksheet)
        column = next(
            cell.column
            for cell in sheet[1]
            if str(cell.value).strip() == "Date of Session 1"
        )
        assert isinstance(column, int)
        cell = next(
            sheet.cell(row, column)
            for row in range(2, sheet.max_row + 1)
            if isinstance(sheet.cell(row, column).value, (date, datetime))
        )
        value = cell.value
        assert isinstance(value, (date, datetime))
        cell.value = f"=DATE({value.year},{value.month},{value.day})"
        workbook.save(workbook_path)
        try:
            after = wrangle.run(
                path, tmp_path / "after", datetime(2026, 10, 10)
            )
        except wrangle.InputError:
            return
        left = wrangle.csv_text(before["fact_was_session"], "fact_was_session")
        right = wrangle.csv_text(after["fact_was_session"], "fact_was_session")
        assert left == right


class TestDataformSources:
    """The Dataform sources hold only printable text."""

    def test_no_control_characters(self, project_folder: Path) -> None:
        """A stray control character would silently change a pattern.

        Args:
            project_folder: The project folder.
        """
        folder = project_folder / "dataform"
        for path in folder.rglob("*"):
            if path.suffix in {".js", ".sqlx", ".yaml"}:
                found = re.search(
                    r"[\x00-\x08\x0b\x0c\x0e-\x1f]",
                    path.read_text("utf-8"),
                )
                assert found is None, path.name


class TestWithoutPyCommon:
    """The folder route works on an install without the landing extra."""

    def test_pipeline_runs_without_py_common(
        self, fixture_config: Path, tmp_path: Path
    ) -> None:
        """The documented no-ingestion install can build the tables.

        Args:
            fixture_config: Frozen synthetic configuration.
            tmp_path: Output folder.
        """
        script = (
            "import sys\n"
            "sys.modules['py_common'] = None\n"
            "from hww_dashboard import wrangle\n"
            "tables = wrangle.run(sys.argv[1], sys.argv[2])\n"
            "print(len(tables))\n"
        )
        done = subprocess.run(
            [sys.executable, "-c", script, str(fixture_config), str(tmp_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.returncode == 0, done.stderr
        assert done.stdout.strip().endswith("12")
