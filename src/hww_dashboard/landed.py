"""Read the inputs from the typed tables py-common loaded.

``python ingest.py`` (:mod:`hww_dashboard.landing`) loads each workbook
into a typed table. With ``[landed] read = true`` in config.toml,
``wrangle.py`` reads those tables instead of the workbooks:
``LandedInputs`` selects committed audit records, including empty loads,
honouring each source's file or file_pattern selection. It shapes rows
as ``wrangle.read_sheet`` would read the workbook
(same headings, Excel types and ``excel_row``), so everything after
that step is unchanged.

The tables are local Parquet files (``target = "local"``) or BigQuery
tables (``target = "gcp"``).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Protocol

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from hww_dashboard.landing import (
    LOADED_AT,
    ROW_FIELD,
    LocalTableWarehouse,
    SourceContract,
    landing_settings,
    source_contracts,
)
from hww_dashboard.wrangle import (
    Config,
    InputError,
    SheetInput,
    date_in_name,
    require,
)


@dataclass
class Load:
    """The newest load of a typed table.

    Attributes:
        rows: Its rows, without the warehouse's ``_loaded_at``.
        file: Name of the workbook it came from.
        sha256: The workbook's SHA-256.
        loaded_at: When it was loaded.
    """

    rows: pa.Table
    file: str
    sha256: str
    loaded_at: datetime


class Tables(Protocol):
    """Where the typed tables are."""

    def newest_load(self, table: str, settings: Config | None = None) -> Load:
        """The rows and facts of a table's newest load.

        Args:
            table: Table name, e.g. "hww_was".
            settings: Optional filename or pattern selection settings.

        Returns:
            The load.

        Raises:
            InputError: The table or a matching committed load is missing.
        """
        ...


def _file_name(load_key: str, checksum: str) -> str:
    """The workbook's name from py-common's load key.

    py-common's key is ``<source identity>_<first 8 of checksum>``, and
    the identity is the file's path in its landing folder or bucket.

    Args:
        load_key: The audit row's ``filename``.
        checksum: The audit row's ``checksum``.

    Returns:
        The file name, e.g. "dummy_was_database.xlsx".
    """
    identity = load_key.removesuffix(f"_{checksum[:8]}")
    return identity.replace("\\", "/").rsplit("/", 1)[-1]


def selected_audit(
    records: list[dict[str, Any]], table: str, settings: Config | None
) -> dict[str, Any]:
    """Choose a committed load using the source's selection policy.

    Args:
        records: Audit rows already scoped to the destination table.
        table: Table name for error messages.
        settings: Configured file or file_pattern, if supplied.

    Returns:
        The selected audit row with its source_file populated.

    Raises:
        InputError: No committed load matches the selection settings.
    """
    settings = settings or {}
    pattern = settings.get("file_pattern")
    wanted = settings.get("file") if pattern is None else None
    matches = []
    for record in records:
        if record.get("outcome") != "LOADED":
            continue
        name = record.get("source_file") or _file_name(
            record["filename"], record["checksum"]
        )
        if pattern is not None and not fnmatch(name, pattern):
            continue
        if wanted is not None and name != wanted:
            continue
        matches.append({**record, "source_file": name})
    if not matches:
        raise InputError(
            f"Landed table {table}: no committed load matches the source "
            "settings. Run python ingest.py first."
        )

    def rank(record: dict[str, Any]) -> tuple[date, float, str, str]:
        """Rank filename dates before ingestion timestamps.

        Args:
            record: A matching committed audit record.

        Returns:
            Filename date, load time and deterministic filename order.
        """
        name = str(record["source_file"])
        moment = datetime.fromisoformat(record["timestamp"])
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        return (
            (date_in_name(Path(name)) or date.min) if pattern else date.min,
            moment.timestamp(),
            name.casefold(),
            name,
        )

    return max(matches, key=rank)


@dataclass
class LocalTables:
    """Typed tables written by LocalTableWarehouse.

    Attributes:
        folder: The tables folder.
    """

    folder: Path

    def newest_load(self, table: str, settings: Config | None = None) -> Load:
        """Read the newest load of a table and its audit row.

        Args:
            table: Table name.
            settings: Optional configured filename or export pattern.

        Returns:
            The load.

        Raises:
            InputError: No such table, or no audit row for its load.
        """
        warehouse = LocalTableWarehouse(self.folder, table)
        if not warehouse.table_path.exists():
            raise InputError(
                f"No landed table {table} in {self.folder}. Run "
                "python ingest.py first, or set [landed] read = false to "
                "read the workbooks."
            )
        data = pq.read_table(warehouse.table_path)
        record = selected_audit(
            [
                row
                for row in warehouse.audit(data)
                if row.get("destination") == table
            ],
            table,
            settings,
        )
        loaded_at = datetime.fromisoformat(record["timestamp"])
        stamps = data.column(LOADED_AT)
        stamp = pa.scalar(loaded_at, type=stamps.type)
        rows = data.filter(pc.equal(stamps, stamp)).drop_columns([LOADED_AT])
        if rows.num_rows != record["row_count"]:
            raise InputError(
                f"Landed table {table}: audited row count differs."
            )
        return Load(rows, record["source_file"], record["checksum"], loaded_at)


@dataclass
class BigQueryTables:
    """Typed tables loaded by py-common's BigQueryWarehouse.

    Attributes:
        project: GCP project.
        dataset: Dataset holding the tables and py-common's ``audit``.
        client: A ``google.cloud.bigquery.Client`` (or a stand-in).
    """

    project: str
    dataset: str
    client: Any

    def newest_load(self, table: str, settings: Config | None = None) -> Load:
        """Query the newest load of a table and its audit row.

        Args:
            table: Table name.
            settings: Optional configured filename or export pattern.

        Returns:
            The load.

        Raises:
            InputError: No matching committed load exists, or its row
                count differs from the audit record.
        """
        from google.cloud import bigquery

        table_id = f"{self.project}.{self.dataset}.{table}"
        audit_id = f"{self.project}.{self.dataset}.audit"
        config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter(
                    "destination", "STRING", table_id
                ),
            ]
        )
        audit = list(
            self.client.query(
                f"SELECT filename, checksum, timestamp, row_count "
                f"FROM `{audit_id}` WHERE destination = @destination "
                "AND outcome = 'LOADED' ORDER BY timestamp DESC"
                + (" LIMIT 1" if settings is None else ""),
                job_config=config,
            ).result()
        )
        record = selected_audit(
            [
                {
                    "filename": row[0],
                    "checksum": row[1],
                    "timestamp": row[2].isoformat(),
                    "row_count": row[3],
                    "outcome": "LOADED",
                }
                for row in audit
            ],
            table_id,
            settings,
        )
        loaded_at = datetime.fromisoformat(record["timestamp"])
        config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter(
                    "loaded_at", "TIMESTAMP", loaded_at
                )
            ]
        )
        rows = self.client.query(
            f"SELECT * FROM `{table_id}` WHERE {LOADED_AT} = @loaded_at",
            job_config=config,
        ).to_arrow()
        if rows.num_rows != record["row_count"]:
            raise InputError(
                f"Landed table {table_id}: audited row count differs."
            )
        return Load(
            rows.drop_columns([LOADED_AT]),
            record["source_file"],
            record["checksum"],
            loaded_at,
        )


def to_sheet(load: Load, contract: SourceContract) -> pd.DataFrame:
    """Shape a load as ``wrangle.read_sheet`` shapes the workbook.

    Table columns are renamed back to the workbook headings wrangle.py
    knows, values become plain Python values (text, whole numbers,
    datetimes, NaN for empty), and rows are put back in Excel order
    with their ``excel_row``.

    Args:
        load: The table's newest load.
        contract: The source's contract.

    Returns:
        The sheet. ``attrs`` holds the sheet name and the columns the
        contract excluded (by wrangle.py's names).
    """
    records = load.rows.to_pylist()
    frame = pd.DataFrame.from_records(records, columns=load.rows.column_names)
    frame = frame.astype(object).where(frame.notna(), float("nan"))
    frame["excel_row"] = [int(row) for row in frame.pop(ROW_FIELD)]
    frame = frame.rename(columns=contract.names)
    known = [*contract.names.values(), "excel_row"]
    frame = frame[[c for c in frame.columns if c in known]]
    frame = frame.sort_values("excel_row", kind="stable").reset_index(
        drop=True
    )
    frame.attrs["sheet_name"] = contract.worksheet.name
    frame.attrs["excluded"] = [
        _wrangle_name(name, contract) for name in contract.worksheet.excluded
    ]
    return frame


def _wrangle_name(name: str, contract: SourceContract) -> str:
    """wrangle.py's name for an excluded py-common heading.

    Args:
        name: Heading as py-common reads it.
        contract: The source's contract.

    Returns:
        The heading as wrangle.read_sheet would give it.
    """
    from hww_dashboard.landing import pandas_name

    if contract.table == "hww_survey":
        repeat = name.rsplit("_", 1)
        if len(repeat) == 2 and repeat[1].isdigit() and int(repeat[1]) >= 2:
            return f"{repeat[0]}.{int(repeat[1]) - 1}"
    return pandas_name(name)


@dataclass
class LandedInputs:
    """wrangle.Inputs that read py-common's typed tables.

    Attributes:
        tables: Where the tables are.
        contracts: Each source's contract, by config section.
    """

    tables: Tables
    contracts: dict[str, SourceContract]

    def read(
        self,
        section: str,
        cfg: Config,
        source: str,
        required: Sequence[str],
    ) -> SheetInput:
        """Read the newest load of one source's table.

        Args:
            section: The source's config section, e.g. ``"was"``.
            cfg: That source's filename or export selection settings.
            source: Name of the source, for messages.
            required: Column headings that must be present.

        Returns:
            The sheet, with the workbook's name and SHA-256, the table
            and when it was loaded.

        Raises:
            InputError: The table or a matching audited load is missing,
                its row count differs, or a required column is absent.
        """
        contract = self.contracts[section]
        load = self.tables.newest_load(contract.table, cfg)
        frame = to_sheet(load, contract)
        require(
            frame,
            required,
            source,
            f"landed table {contract.table}, loaded "
            f"{load.loaded_at.isoformat(timespec='seconds')}",
        )
        facts = {
            "file": load.file,
            "sha256": load.sha256,
            "table": contract.table,
            "loaded_at": load.loaded_at.isoformat(timespec="seconds"),
        }
        return SheetInput(frame, load.file, facts)


def landed_inputs(cfg: Config, base: Path, maps: Path) -> LandedInputs:
    """Inputs reading the tables [landed] points at.

    Args:
        cfg: The checked config.
        base: Folder of the config file.
        maps: The mappings folder.

    Returns:
        The inputs.
    """
    settings = landing_settings(cfg, base)
    tables: Tables
    if settings.target == "gcp":
        from google.cloud import bigquery

        tables = BigQueryTables(
            settings.project,
            settings.dataset,
            bigquery.Client(project=settings.project),
        )
    else:
        tables = LocalTables(settings.tables)
    return LandedInputs(tables, source_contracts(cfg, maps))
