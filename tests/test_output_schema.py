"""Checks on the output contract: the schemas and the checks on them."""

from pathlib import Path

import pandas as pd
import pytest

from hww_dashboard import output_schema, wrangle

GOLDEN = Path(__file__).resolve().parent / "golden"


class TestSchema:
    """``schema`` and ``tables``: one schema per output table."""

    def test_every_table_has_a_schema(self) -> None:
        """The schemas cover exactly the tables the pipeline writes."""
        assert output_schema.tables() == sorted(wrangle.COLUMNS)

    @pytest.mark.parametrize("table", sorted(wrangle.COLUMNS))
    def test_columns_match_the_pipeline(self, table: str) -> None:
        """Each schema lists the pipeline's columns, in the same order.

        Args:
            table: A table name.
        """
        names = [field.name for field in output_schema.schema(table)]
        assert names == wrangle.COLUMNS[table]

    @pytest.mark.parametrize("table", sorted(wrangle.COLUMNS))
    def test_every_column_is_described(self, table: str) -> None:
        """Each column says what it holds, for BigQuery and Dataform.

        Args:
            table: A table name.
        """
        for field in output_schema.schema(table):
            assert field.description, f"{table}.{field.name}"

    def test_unknown_table(self) -> None:
        """A table without a schema is a SchemaError."""
        with pytest.raises(output_schema.SchemaError, match="No schema"):
            output_schema.schema("no_such_table")


class TestIsDate:
    """``is_date``: YYYY-MM-DD and a real calendar day."""

    @pytest.mark.parametrize(
        ("text", "valid"),
        [
            ("2026-03-04", True),
            ("2026-02-30", False),
            ("2026-3-4", False),
            ("04/03/2026", False),
            ("2026-03-04T00:00:00", False),
        ],
    )
    def test_dates(self, text: str, valid: bool) -> None:
        """Only real dates in ISO form pass.

        Args:
            text: A cell.
            valid: Whether it should pass.
        """
        assert output_schema.is_date(text) is valid


class TestCheckCells:
    """``check_cells``: a table's text against its schema."""

    def test_golden_outputs_keep_to_the_contract(self) -> None:
        """Every table in the snapshot passes its schema."""
        for path in sorted(GOLDEN.glob("*.csv")):
            text = path.read_text("utf-8")
            output_schema.check_cells(output_schema.parse_csv(text), path.stem)

    @pytest.mark.parametrize(
        ("column", "value", "problem"),
        [
            ("date", "2026-13-01", "not DATE"),
            ("year", "2026.0", "not INT64"),
            ("month_name", "", "REQUIRED"),
        ],
    )
    def test_problems_are_named_without_values(
        self, column: str, value: str, problem: str
    ) -> None:
        """The message names the table, column and count, not the value.

        Args:
            column: The column to break.
            value: The bad cell.
            problem: Expected words in the message.
        """
        row = {
            "date": "2026-04-01",
            "year": "2026",
            "month": "4",
            "month_name": "April",
            "month_start": "2026-04-01",
            "fin_year": "2026-27",
            "fin_quarter": "Q1",
        }
        row[column] = value
        cells = pd.DataFrame([row], dtype=str)
        with pytest.raises(output_schema.SchemaError) as error:
            output_schema.check_cells(cells, "dim_date")
        message = str(error.value)
        assert f"dim_date.{column}: 1" in message
        assert problem in message
        if value:
            assert value not in message

    def test_booleans_are_true_or_false(self) -> None:
        """BOOL cells are True or False; NULLABLE ones may be empty."""
        cells = pd.DataFrame(
            {c: [""] for c in wrangle.COLUMNS["fact_signup"]}, dtype=str
        )
        cells["signup_id"] = "SU0001"
        cells["survey_flag"] = "yes"
        with pytest.raises(output_schema.SchemaError, match="not BOOL"):
            output_schema.check_cells(cells, "fact_signup")
        cells["survey_flag"] = "True"
        output_schema.check_cells(cells, "fact_signup")

    def test_columns_must_match(self) -> None:
        """A missing or extra column is a SchemaError."""
        cells = pd.DataFrame({"badge": ["Award"]}, dtype=str)
        with pytest.raises(output_schema.SchemaError, match="differ"):
            output_schema.check_cells(cells, "badges")


class TestCsvText:
    """``wrangle.csv_text``: the CSV text both writers start from."""

    def test_lines_end_in_lf_on_every_system(self) -> None:
        """No carriage returns, so Windows and Linux give the same bytes."""
        frame = pd.DataFrame({"badge": ["A", "B"]})
        text = wrangle.csv_text(frame, "badges")
        assert "\r" not in text
        assert text == "employer_id,badge,awarded_date\n,A,\n,B,\n"
