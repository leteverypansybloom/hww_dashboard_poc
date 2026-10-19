"""The output contract: each table's columns, types and required fields.

One JSON file per table in ``hww_dashboard/schema/``, in BigQuery's
schema format, is the contract both writers keep to: the CSV files on
laptops and in the tests, and the BigQuery tables in GCP. The Dataform
models should produce the same tables. ``docs/output_contract.md``
explains the conventions.

A table is checked in its CSV text form, which both writers start
from. There an empty cell is NULL, a BOOL is ``True`` or ``False``, a
DATE is ``YYYY-MM-DD`` and an INT64 is a whole number.
"""

import io
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from functools import cache
from pathlib import Path

import pandas as pd

SCHEMA_FOLDER = Path(__file__).resolve().parent / "schema"
#: Schemas of the tables that exist only in BigQuery: the report and the
#: run records.
BIGQUERY_FOLDER = SCHEMA_FOLDER / "bigquery"


class SchemaError(Exception):
    """A table broke the output contract.

    That is a bug in the pipeline, never a problem with the inputs, so
    ``python wrangle.py`` treats it as an unexpected error (exit code 2).
    """


@dataclass(frozen=True)
class Field:
    """One column of an output table.

    Attributes:
        name: Column name.
        type: BigQuery type: STRING, DATE, BOOL or INT64.
        mode: REQUIRED (never empty) or NULLABLE.
        description: What the column holds.
    """

    name: str
    type: str
    mode: str
    description: str

    @property
    def required(self) -> bool:
        """Whether the column may never be empty.

        Returns:
            True for REQUIRED columns.
        """
        return self.mode == "REQUIRED"


def is_date(text: str) -> bool:
    """Check text is a date written YYYY-MM-DD.

    Args:
        text: A CSV cell.

    Returns:
        True if it is a real calendar date in that form.
    """
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return False
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def is_timestamp(text: str) -> bool:
    """Check text is an ISO 8601 time with a time zone.

    Args:
        text: A cell.

    Returns:
        True for text such as ``2026-10-18T09:15:02+00:00``.
    """
    try:
        return datetime.fromisoformat(text).tzinfo is not None
    except ValueError:
        return False


#: How each type looks in CSV text (empty cells are checked separately).
VALID: dict[str, Callable[[str], bool]] = {
    "STRING": lambda text: True,
    "DATE": is_date,
    "BOOL": lambda text: text in ("True", "False"),
    "INT64": lambda text: re.fullmatch(r"-?\d+", text) is not None,
    "TIMESTAMP": is_timestamp,
}


@cache
def schema(table: str, folder: Path = SCHEMA_FOLDER) -> tuple[Field, ...]:
    """Read one table's schema.

    Args:
        table: Table name, e.g. ``"dim_employer"``.
        folder: Where to look: the output tables' schemas, or
            ``BIGQUERY_FOLDER`` for the tables that exist only in
            BigQuery.

    Returns:
        The table's fields, in column order.

    Raises:
        SchemaError: The table has no schema, or the schema names an
            unknown type or mode.
    """
    path = folder / f"{table}.json"
    if not path.exists():
        raise SchemaError(f"No schema for table {table}.")
    fields = tuple(
        Field(
            entry["name"],
            entry["type"],
            entry.get("mode", "NULLABLE"),
            entry.get("description", ""),
        )
        for entry in json.loads(path.read_text(encoding="utf-8"))
    )
    for field in fields:
        if field.type not in VALID or field.mode not in (
            "REQUIRED",
            "NULLABLE",
        ):
            raise SchemaError(
                f"{table}.{field.name}: unknown type {field.type} or mode "
                f"{field.mode} in its schema."
            )
    return fields


def parse_csv(text: str) -> pd.DataFrame:
    """Read CSV text back as text cells, exactly as written.

    Args:
        text: A table as CSV text.

    Returns:
        The table, every cell a string; empty cells are ``""``.
    """
    return pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)


def check_cells(cells: pd.DataFrame, table: str) -> None:
    """Check a table's text cells against its schema.

    Args:
        cells: The table as text, from :func:`parse_csv`.
        table: Its name.

    Raises:
        SchemaError: The columns differ from the schema, a REQUIRED
            column has an empty cell, or a cell doesn't fit its type.
            The message names the table, the column and how many cells,
            never the values.
    """
    fields = schema(table)
    expected = [field.name for field in fields]
    if list(cells.columns) != expected:
        raise SchemaError(
            f"{table}: columns {list(cells.columns)} differ from its "
            f"schema {expected}."
        )
    for field in fields:
        values = cells[field.name]
        blank = values == ""
        if field.required and blank.any():
            raise SchemaError(
                f"{table}.{field.name}: {int(blank.sum())} empty cell(s) in "
                "a REQUIRED column."
            )
        wrong = ~blank & ~values.map(VALID[field.type]).astype(bool)
        if wrong.any():
            raise SchemaError(
                f"{table}.{field.name}: {int(wrong.sum())} cell(s) are not "
                f"{field.type}."
            )
