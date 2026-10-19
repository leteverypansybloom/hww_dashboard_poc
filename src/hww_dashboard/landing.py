"""Land the HWW workbooks in typed tables with py-common.

This is the ingestion job: ``python ingest.py`` (or
``python -m hww_dashboard.landing``). For each of the four sources it
runs one py-common ``Pipeline`` on py-common's typed route
(``output_format="parquet"``):

1. the source lists the workbooks dropped in that source's landing
   folder (a local folder, or a prefix in a GCS bucket);
2. the workbook is checked against the source's contract (below):
   every column must be one the contract lists or excludes, and every
   listed column must hold its declared type, or the file is
   quarantined and nothing loads;
3. the listed columns are loaded into the source's typed table
   (``hww_signups``, ``hww_survey``, ``hww_was``, ``hww_peer``), with
   the raw file, the Parquet and an audit record kept in the store.

Personal and unused columns are excluded from the typed tables. The
store still archives complete original workbooks, including excluded
columns, for successful and quarantined uploads. ``wrangle.py`` reads
committed loads when ``[landed] read = true`` (see
:mod:`hww_dashboard.landed`).

Each upload is appended (no merge keys): the WAS database has a row
with no Participant ID, so no source has a reliable key. Every upload
of these workbooks is the complete list, so readers take only the
newest load.

Locally, ``LocalTableWarehouse`` stands in for py-common's
``BigQueryWarehouse``: same protocol, Parquet files in a folder.
"""

import argparse
import json
import logging
import os
import re
import shutil
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from fnmatch import fnmatch
from functools import partial
from io import BytesIO
from pathlib import Path
from typing import Any, Literal

import pyarrow as pa
import pyarrow.parquet as pq
from py_common.adapters import LocalObjectStore, LocalSource
from py_common.contract import Column, Contract, SheetRows, Worksheet
from py_common.errors import ServiceError, ValidationError
from py_common.model import Outcome, Result, SourceItem
from py_common.parquet import column_name
from py_common.pipeline import Pipeline
from py_common.ports import ObjectStore, Source, Warehouse

from hww_dashboard.wrangle import (
    MAPPING_COLUMNS,
    SOURCES,
    Config,
    InputError,
    clean_text,
    date_in_name,
    input_file,
    load_config,
    read_csv_text,
)

logger = logging.getLogger("hww_dashboard.landing")

#: Typed table for each source.
TABLES = {source: f"hww_{source}" for source in SOURCES}

#: Column added to every sheet: the row's number as Excel shows it.
#: Typed tables keep no row order, and the pipeline needs it (signups'
#: month is a merged cell filled downwards; ids fall back to it).
ROW_COLUMN = "Excel row"

#: BigQuery-style name of ROW_COLUMN: the pipeline's own name for it.
ROW_FIELD = column_name(ROW_COLUMN)

#: Column the warehouse adds to each loaded row: when it was loaded.
LOADED_AT = "_loaded_at"

#: Audit history embedded in Parquet so data and metadata commit together.
AUDIT_METADATA = b"hww.audit"

#: py-common's name for a repeated heading: "Other_2" for the second
#: "Other". pandas, which wrangle.read_sheet follows, says "Other.1".
_PANDAS_REPEAT = re.compile(r"^(?P<base>.*)\.(?P<n>\d+)$")
_BLANK_HEADING = re.compile(r"^col_(?P<letter>[A-Z]+)$")


def _strings(*names: str) -> list[Column]:
    """Optional text columns."""
    return [Column(name, "string", nullable=True) for name in names]


def _dates(*names: str) -> list[Column]:
    """Optional date columns."""
    return [Column(name, "date", nullable=True) for name in names]


# Headings are exactly as in the workbooks: py-common matches them
# character for character, trailing spaces included. Sheet names are
# the exports' own ("query", "in"), as py-common finds sheets by name.

SIGNUPS = Worksheet(
    name="Account signups",
    header_row=2,
    # "Number of sites" holds numbers and text (1, "2-5"), which no
    # declared type accepts. RowNumberedContract separately requires
    # this heading and refuses any other undeclared loaded column.
    column_selection="all_except",
    columns=[
        Column("col_B", "date", nullable=True),
        *_strings(
            "Org (duplicates in red)",
            "Role (complete if duplicate org)",
            "Size",
            "Sector",
            "Industry",
            "Completed survey?",
            "Requested WAS?",
        ),
    ],
    excluded=["Count", "Attended  First Steps", "Peer Mentoring"],
    on_mismatch="quarantine",
)

WAS = Worksheet(
    name="query",
    columns=[
        Column("Participant ID", "integer", nullable=True),
        *_dates(
            "Date of Enquiry",
            "Date allocated to adviser",
            "Date of Session 1 ",
            "Date summary sent to organisation",
            "Date of session 2",
            "Date Summary 2 sent ",
            "Date of Session 3 ",
        ),
        *_strings(
            "Title",
            "Number of employees",
            "Sector",
            "Organisation Industry ",
            "Number of sites",
            "Duration of session 1 ",
            "Topics discussed in session 1",
            "Duration of session 2",
            "Topics discussed in session 2",
        ),
    ],
    excluded=[
        "Have they worked with HWW before?",
        "How did they hear of HWW / WAS service?",
        "Key contact ",
        "Job role",
        "Preferred contact details",
        "Accessibility requirements including language ",
        "HWW Adviser",
        "Date booking request sent to organisation",
        "Item Type",
        "Path",
    ],
    on_mismatch="quarantine",
)

PEER = Worksheet(
    name="query (1)",
    columns=[
        *_strings(
            "Participant ID",
            "Business Name",
            "Business Size",
            "Sector",
            "Industry",
        ),
        *_dates("Date of expression of interest"),
    ],
    excluded=[
        "First Name",
        "Last Name",
        "Job Role Title",
        "Email Address",
        "Historic Award Holder",
        "Survey Tool Completed",
        "WAS involvement",
        "Local Authority",
        "Programme Role",
        "Current Status",
        "Primary Mentoring Theme",
        "Secondary Theme(s)",
        "Experience Level",
        "What Support Is Employer Seeking?",
        "What Can Employer Offer Others?",
        "Time Commitment Available",
        "Agreement Signed",
        "Matching Date",
        "Matching ID (Cohort)",
        "HWW Adviser (Cohort)",
        "Title",
        "Item Type",
        "Path",
    ],
    on_mismatch="quarantine",
)

#: Sheet name of the survey export.
SURVEY_SHEET = "in"


@dataclass
class RowNumberedContract(Contract):
    """A py-common Contract that also loads each row's Excel row number.

    The number is added after the checks, as an undeclared column
    (loaded as text), so the contract itself is unchanged.

    Attributes:
        untyped_columns: Extra required headings loaded as text. Their
            cell types may vary; other undeclared headings are refused.
    """

    untyped_columns: list[str] = field(default_factory=list)

    def read(
        self,
        excel_bytes: bytes,
        source_name: str,
        warnings: list[str] | None = None,
    ) -> dict[str, SheetRows]:
        """Check and read the workbook, adding the row numbers.

        Args:
            excel_bytes: Raw Excel file bytes.
            source_name: The file's name.
            warnings: As Contract.read().

        Returns:
            As Contract.read(), with ROW_COLUMN last in every sheet.

        Raises:
            ValidationError: A required untyped heading is absent, or
                an unrecognised column would enter a typed table.
        """
        sheets = super().read(excel_bytes, source_name, warnings)
        for worksheet in self.worksheets:
            expected = {c.name for c in worksheet.columns}
            expected.update(self.untyped_columns)
            actual = set(sheets[worksheet.name].columns)
            missing = expected - actual
            unexpected = actual - expected
            if missing or unexpected:
                problems = []
                if missing:
                    problems.append(f"Missing columns: {sorted(missing)}")
                if unexpected:
                    problems.append(
                        f"Unexpected columns: {sorted(unexpected)}"
                    )
                raise ValidationError(
                    f"{source_name} [{worksheet.name}]: " + "; ".join(problems)
                )
        return _numbered(sheets)

    def extract(
        self, excel_bytes: bytes, source_name: str = "workbook"
    ) -> dict[str, SheetRows]:
        """Read the workbook without checking, adding the row numbers.

        Args:
            excel_bytes: Raw Excel file bytes.
            source_name: The file's name.

        Returns:
            As Contract.extract(), with ROW_COLUMN last in every sheet.
        """
        return _numbered(super().extract(excel_bytes, source_name))


def _numbered(sheets: dict[str, SheetRows]) -> dict[str, SheetRows]:
    """Add each row's Excel row number as the last column.

    Args:
        sheets: Sheets as py-common reads them.

    Returns:
        The same sheets with ROW_COLUMN added.
    """
    return {
        name: SheetRows(
            columns=[*sheet.columns, ROW_COLUMN],
            rows=[(row, (*values, row)) for row, values in sheet.rows],
        )
        for name, sheet in sheets.items()
    }


@dataclass
class SourceContract:
    """What py-common checks and loads for one source.

    Attributes:
        contract: The workbook contract.
        table: Typed table the rows load into.
        names: Column name in the table -> the heading wrangle.py knows
            it by (trimmed, repeats numbered as pandas does).
        undeclared: Headings loaded as text without a type check
            (signups' "Number of sites").
    """

    contract: RowNumberedContract
    table: str
    names: dict[str, str] = field(default_factory=dict)
    undeclared: list[str] = field(default_factory=list)

    @property
    def worksheet(self) -> Worksheet:
        """The contract's one worksheet."""
        return self.contract.worksheets[0]


def pandas_name(name: str) -> str:
    """The heading wrangle.read_sheet would give a py-common heading.

    Args:
        name: Heading as py-common reads it.

    Returns:
        Trimmed, with "col_B" as "B".
    """
    blank = _BLANK_HEADING.match(name)
    return blank["letter"] if blank else clean_text(name)


def py_common_name(name: str) -> str:
    """The heading py-common gives a column wrangle.read_sheet names.

    Args:
        name: Heading as wrangle.read_sheet gives it, e.g. "Other.2".

    Returns:
        py-common's name for the same column, e.g. "Other_3".
    """
    repeat = _PANDAS_REPEAT.match(name)
    if repeat and int(repeat["n"]) >= 1:
        return f"{repeat['base']}_{int(repeat['n']) + 1}"
    return name


def survey_worksheet(
    maps: Path, keep_other_text: bool
) -> tuple[Worksheet, dict[str, str]]:
    """The survey export's contract, from mappings/survey_columns.csv.

    The column map lists every column of the export with its role, so
    the contract follows it: role columns and answers are loaded, the
    rest (personal, technical) excluded. "Other" free text loads only
    when keep_other_free_text is on.

    Args:
        maps: The mappings folder.
        keep_other_text: The survey's keep_other_free_text setting.

    Returns:
        The worksheet, and py-common name -> wrangle.py name for each
        loaded column.
    """
    table = read_csv_text(
        maps / "survey_columns.csv", MAPPING_COLUMNS["survey_columns"]
    )
    columns: list[Column] = []
    excluded: list[str] = []
    names: dict[str, str] = {}
    data_types: dict[str, Literal["integer", "date", "string"]] = {
        "response_id": "integer",
        "date": "date",
    }
    for heading, role in zip(table["column"], table["role"], strict=True):
        name = py_common_name(heading)
        if role == "drop" or (role == "other_text" and not keep_other_text):
            excluded.append(name)
            continue
        columns.append(
            Column(name, data_types.get(role, "string"), nullable=True)
        )
        names[name] = heading
    worksheet = Worksheet(
        name=SURVEY_SHEET,
        columns=columns,
        excluded=excluded,
        on_mismatch="quarantine",
    )
    return worksheet, names


def source_contracts(cfg: Config, maps: Path) -> dict[str, SourceContract]:
    """Every source's contract.

    A source named by ``file`` in config.toml must arrive under that
    name. Sources with ``file_pattern`` select their newest matching
    workbook before contract validation.

    Args:
        cfg: The checked config.
        maps: The mappings folder.

    Returns:
        SourceContract per source, in SOURCES order.
    """
    survey, survey_names = survey_worksheet(
        maps, bool(cfg["survey"]["keep_other_free_text"])
    )
    sheets = {"signups": SIGNUPS, "survey": survey, "was": WAS, "peer": PEER}
    result: dict[str, SourceContract] = {}
    for source in SOURCES:
        sheet = replace(
            sheets[source], allow_empty=cfg[source].get("allow_empty", False)
        )
        file_name = (
            None if "file_pattern" in cfg[source] else cfg[source].get("file")
        )
        undeclared = ["Number of sites"] if source == "signups" else []
        contract = RowNumberedContract(
            worksheets=[sheet],
            file_name=str(file_name) if file_name else None,
            untyped_columns=undeclared,
        )
        if source == "survey":
            known = survey_names
        else:
            known = {c.name: pandas_name(c.name) for c in sheet.columns}
            known.update({h: pandas_name(h) for h in undeclared})
        names = {
            column_name(h): wrangle_name for h, wrangle_name in known.items()
        }
        if len(names) != len(known):
            raise InputError(
                f"{source}: two loaded columns get the same table column "
                "name; rename one in the workbook."
            )
        result[source] = SourceContract(
            contract, TABLES[source], names, undeclared
        )
    return result


# ------------------------------------------------ local warehouse


class LocalTableWarehouse:
    """py-common Warehouse that keeps typed tables as Parquet files.

    Stands in for ``BigQueryWarehouse`` on a laptop, with the same
    behaviour for append-only tables (no merge keys): each load's rows
    are appended with ``_loaded_at``. Audit history is embedded in the
    same Parquet file; one atomic replacement publishes both. Legacy
    audit.jsonl records are imported on the first successful new load.
    A previously committed upload is skipped on retry.

    Attributes:
        folder: Folder holding ``<table>.parquet`` and any legacy audit.
        table_id: Table this warehouse loads.
        key_columns: Always empty: append-only.
    """

    def __init__(self, folder: Path | str, table_id: str) -> None:
        """Point at a table in a folder (created when first loaded).

        Args:
            folder: Folder for the tables and the audit file.
            table_id: Table name, e.g. "hww_was".
        """
        self.folder = Path(folder)
        self.table_id = table_id
        self.key_columns: list[str] = []

    @property
    def identity(self) -> str:
        """Identifier like BigQuery's project.dataset.table.

        py-common puts it in storage keys and the lock name, so it must
        be a plain name: no drive letter, colon or slash.
        """
        return f"local.{self.folder.resolve().name}.{self.table_id}"

    @property
    def table_path(self) -> Path:
        """The table's Parquet file."""
        return self.folder / f"{self.table_id}.parquet"

    @property
    def audit_path(self) -> Path:
        """The audit file shared by every table in the folder."""
        return self.folder / "audit.jsonl"

    def load(
        self,
        key: str,
        checksum: str,
        data: bytes,
        rows: int,
        item: SourceItem,
    ) -> bool:
        """Append one file's rows and record the load.

        Args:
            key: Load key (source identity and checksum).
            checksum: SHA-256 of the source file.
            data: Parquet bytes of the sheet's rows.
            rows: Expected row count.
            item: Source file the rows came from.

        Returns:
            True if written, False if this upload was already loaded.

        Raises:
            ValidationError: The rows can't join the table (a reserved
                column, or a column whose type changed).
            ServiceError: The Parquet is unreadable, has the wrong row
                count, or the folder can't be written.
        """
        if self._already_loaded(key, item.version):
            return False
        try:
            new = pq.read_table(BytesIO(data))
        except (pa.ArrowException, OSError) as error:
            raise ServiceError(
                f"{self.table_id}: bad Parquet: {error}"
            ) from error
        if new.num_rows != rows:
            raise ServiceError(
                f"{self.table_id}: row count mismatch: expected {rows}, "
                f"got {new.num_rows}"
            )
        if LOADED_AT in new.column_names:
            raise ValidationError(
                f"{item.name}: has a column named {LOADED_AT}, which the "
                "warehouse sets"
            )
        timestamp = datetime.now(UTC)
        stamp = pa.array(
            [timestamp] * new.num_rows, type=pa.timestamp("us", tz="UTC")
        )
        new = new.append_column(LOADED_AT, stamp)
        previous = (
            pq.read_table(self.table_path)
            if self.table_path.exists()
            else None
        )
        records = [
            row
            for row in self.audit(previous)
            if row.get("destination") == self.table_id
        ]
        try:
            table = (
                pa.concat_tables([previous, new], promote_options="default")
                if previous is not None
                else new
            )
        except (pa.ArrowInvalid, pa.ArrowTypeError) as error:
            raise ValidationError(
                f"{item.name}: its columns don't fit {self.table_id} "
                f"({error})"
            ) from error
        temporary = self.table_path.with_suffix(".parquet.tmp")
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            records.append(
                {
                    "filename": key,
                    "checksum": checksum,
                    "destination": self.table_id,
                    "source_version": item.version,
                    "source_file": item.name,
                    "row_count": rows,
                    "outcome": Outcome.LOADED.value.upper(),
                    "timestamp": timestamp.isoformat(),
                }
            )
            metadata = dict(table.schema.metadata or {})
            metadata[AUDIT_METADATA] = json.dumps(
                records, sort_keys=True
            ).encode("utf-8")
            table = table.replace_schema_metadata(metadata)
            pq.write_table(table, temporary)
            os.replace(temporary, self.table_path)
        except OSError as error:
            raise ServiceError(
                f"{self.table_id}: cannot write {self.folder} ({error})"
            ) from error
        finally:
            temporary.unlink(missing_ok=True)
        return True

    def audit(self, table: pa.Table | None = None) -> list[dict[str, Any]]:
        """Read committed audit history, oldest first.

        Args:
            table: An already-read snapshot, so readers use its own
                metadata even if another load commits concurrently.

        Returns:
            Embedded records, or legacy audit.jsonl records when the
            table has not yet migrated to embedded metadata.
        """
        metadata = (
            table.schema.metadata
            if table is not None
            else (
                pq.read_schema(self.table_path).metadata
                if self.table_path.exists()
                else None
            )
        )
        if metadata and AUDIT_METADATA in metadata:
            records: list[dict[str, Any]] = json.loads(
                metadata[AUDIT_METADATA]
            )
            return records
        if not self.audit_path.exists():
            return []
        lines = self.audit_path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    def _already_loaded(self, key: str, version: str) -> bool:
        """Whether this upload is already in this table.

        Args:
            key: Load key.
            version: Source version of the upload.

        Returns:
            True if the audit has a LOADED row for it.
        """
        return any(
            row.get("destination") == self.table_id
            and row.get("filename") == key
            and row.get("source_version") == version
            and row.get("outcome") == "LOADED"
            for row in self.audit()
        )


# ------------------------------------------------ the job


@dataclass
class NewestSource:
    """A source exposing only its newest matching workbook.

    Attributes:
        source: Underlying local or GCS source.
        pattern: Configured file_pattern.
        modified: Get the discovered version's modification timestamp.
    """

    source: Source
    pattern: str
    modified: Callable[[SourceItem], float]

    def items(self) -> Iterable[SourceItem]:
        """Select by filename date, modification time and filename.

        Returns:
            One selected workbook, or no items if nothing matches.
        """
        matches = [
            item
            for item in self.source.items()
            if not item.name.startswith("~$")
            and fnmatch(item.name, self.pattern)
        ]
        if not matches:
            return []
        chosen = max(
            matches,
            key=lambda item: (
                date_in_name(Path(item.name)) or date.min,
                self.modified(item),
                item.name.casefold(),
                item.name,
            ),
        )
        return [chosen]

    def download(self, item: SourceItem) -> bytes:
        """Download the selected version through the underlying source.

        Args:
            item: Workbook selected by items().

        Returns:
            Its original bytes, with the source's version checks.
        """
        return self.source.download(item)


def gcs_modified(source: Any, item: SourceItem) -> float:
    """Read the modification time of a discovered GCS generation.

    Args:
        source: The GCSSource holding the landing bucket.
        item: Discovered workbook and generation.

    Returns:
        Modification time in seconds since the Unix epoch.

    Raises:
        ServiceError: The generation or its modification time is absent.
    """
    blob = source.bucket.get_blob(item.identity, generation=int(item.version))
    if blob is None or blob.updated is None:
        raise ServiceError(f"Cannot read modification time for {item.name}")
    return float(blob.updated.timestamp())


def local_modified(folder: Path, item: SourceItem) -> float:
    """Read the modification time used by local export selection.

    Args:
        folder: The source's landing folder.
        item: Discovered workbook relative to that folder.

    Returns:
        Its saved timestamp in seconds since the Unix epoch.
    """
    return (folder / item.identity).stat().st_mtime


@dataclass
class LandingSettings:
    """Where the job reads, keeps and loads, from [landed] in config.

    Attributes:
        target: "local" (folders) or "gcp" (buckets and BigQuery).
        landing: Local: folder with one subfolder per source.
        store: Local: folder for kept copies and audit records.
        tables: Local: folder for the typed tables.
        project: GCP project.
        landing_bucket: GCS bucket the workbooks are dropped in.
        landing_prefix: Folder in that bucket; sources are below it.
        store_bucket: GCS bucket for kept copies and audit records.
        dataset: BigQuery dataset for the typed tables.
    """

    target: str
    landing: Path
    store: Path
    tables: Path
    project: str = ""
    landing_bucket: str = ""
    landing_prefix: str = ""
    store_bucket: str = ""
    dataset: str = ""


def landing_settings(cfg: Config, base: Path) -> LandingSettings:
    """Read [landed] (already checked by check_config).

    Args:
        cfg: The config.
        base: Folder of the config file; local paths are relative to it.

    Returns:
        The settings.
    """
    landed = cfg.get("landed", {})
    return LandingSettings(
        target=str(landed.get("target", "local")),
        landing=(
            base / str(landed.get("landing_folder", "landing"))
        ).resolve(),
        store=(base / str(landed.get("store_folder", "store"))).resolve(),
        tables=(base / str(landed.get("tables_folder", "landed"))).resolve(),
        project=str(landed.get("project", "")),
        landing_bucket=str(landed.get("landing_bucket", "")),
        landing_prefix=str(landed.get("landing_prefix", "")).strip("/"),
        store_bucket=str(landed.get("store_bucket", "")),
        dataset=str(landed.get("dataset", "")),
    )


def long_path(folder: Path) -> Path:
    r"""A folder path that Windows' 260-character limit doesn't apply to.

    py-common keys a kept copy by warehouse, file, checksum, version
    and contract, so its path can pass 260 characters, which Windows
    refuses unless long paths are enabled. The extended-length form
    (``\?\C:\...``) has no such limit. Other systems get the folder
    as it is.

    Args:
        folder: An absolute folder.

    Returns:
        The folder, in extended-length form on Windows.
    """
    prefix = "\\\\?\\"
    if os.name != "nt" or str(folder).startswith(prefix):
        return folder
    return Path(prefix + str(folder.resolve()))


def build_pipelines(
    cfg: Config, maps: Path, settings: LandingSettings
) -> dict[str, Pipeline]:
    """One py-common typed Pipeline per source.

    Args:
        cfg: The checked config.
        maps: The mappings folder.
        settings: From landing_settings().

    Returns:
        Pipeline per source, in SOURCES order.
    """
    contracts = source_contracts(cfg, maps)
    store: ObjectStore
    if settings.target == "gcp":
        from py_common.adapters.bigquery import BigQueryWarehouse
        from py_common.adapters.gcs import GCSObjectStore, GCSSource

        store = GCSObjectStore(settings.project, settings.store_bucket)
    else:
        store = LocalObjectStore(long_path(settings.store))
    pipelines: dict[str, Pipeline] = {}
    for source, contract in contracts.items():
        files: Source
        warehouse: Warehouse
        if settings.target == "gcp":
            prefix = "/".join(
                p for p in (settings.landing_prefix, source) if p
            )
            files = GCSSource(
                settings.project, settings.landing_bucket, prefix
            )
            warehouse = BigQueryWarehouse(
                settings.project, settings.dataset, contract.table
            )
        else:
            files = LocalSource(settings.landing / source)
            warehouse = LocalTableWarehouse(settings.tables, contract.table)
        if "file_pattern" in cfg[source]:
            modified: Callable[[SourceItem], float]
            if settings.target == "gcp":
                modified = partial(gcs_modified, files)
            else:
                modified = partial(local_modified, settings.landing / source)
            files = NewestSource(files, cfg[source]["file_pattern"], modified)
        pipelines[source] = Pipeline(
            source=files,
            store=store,
            warehouse=warehouse,
            contract=contract.contract,
            output_format="parquet",
        )
    return pipelines


def stage(cfg: Config, inputs: Path, landing: Path) -> list[Path]:
    """Copy each source's workbook from a folder into its landing folder.

    The local stand-in for dropping the files in the landing bucket:
    the files the config names (the newest survey export, by pattern)
    are copied to ``<landing>/<source>/``.

    Args:
        cfg: The checked config.
        inputs: Folder holding the workbooks.
        landing: Landing folder.

    Returns:
        The copies made.
    """
    labels = {
        "signups": "Account signups",
        "survey": "Survey export",
        "was": "WAS database",
        "peer": "Peer mentoring",
    }
    copies = []
    for source in SOURCES:
        path = input_file(inputs, cfg[source], labels[source])
        target = landing / source / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copies.append(target)
    return copies


def ingest(
    config_path: str | Path, stage_from: Path | None = None
) -> dict[str, list[Result]]:
    """Run every source's py-common pipeline.

    Args:
        config_path: config.toml.
        stage_from: Folder to copy the workbooks from into the local
            landing folder first (local target only).

    Returns:
        Each source's py-common Results, one per file seen.

    Raises:
        InputError: The config is invalid, or staging was asked for
            with the GCP target.
    """
    config_path = Path(config_path).resolve()
    cfg = load_config(config_path)
    base = config_path.parent
    maps = (base / cfg["paths"]["mappings_folder"]).resolve()
    settings = landing_settings(cfg, base)
    if stage_from is not None:
        if settings.target != "local":
            raise InputError(
                "--stage only works with [landed] target = 'local'."
            )
        for copy in stage(cfg, stage_from, settings.landing):
            logger.info("Staged %s", copy)
    results: dict[str, list[Result]] = {}
    for source, pipeline in build_pipelines(cfg, maps, settings).items():
        results[source] = pipeline.run()
    return results


def summary(results: Mapping[str, Sequence[Result]]) -> tuple[str, bool]:
    """Describe a job's results, one line per file.

    Args:
        results: From ingest().

    Returns:
        The text, and whether every file loaded or was skipped (no
        quarantine or failure).
    """
    lines = []
    ok = True
    for source, source_results in results.items():
        if not source_results:
            lines.append(f"{source}: no files in its landing folder")
            ok = False
        for result in source_results:
            line = (
                f"{source}: {result.item.name}: {result.outcome.value}, "
                f"{result.rows_processed} row(s)"
            )
            if result.errors:
                line += f" - {'; '.join(result.errors)}"
            lines.append(line)
            ok = ok and result.outcome in (Outcome.LOADED, Outcome.SKIPPED)
    return "\n".join(lines), ok


def main(argv: Sequence[str] | None = None) -> int:
    """Command line: ``python ingest.py [config.toml] [--stage FOLDER]``.

    Args:
        argv: Arguments (defaults to sys.argv[1:]).

    Returns:
        0 if every file loaded or was already loaded, 1 otherwise.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("config", nargs="?", default="config.toml")
    parser.add_argument(
        "--stage",
        type=Path,
        help="copy the workbooks from this folder into the landing folder "
        "first (local target only)",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        results = ingest(args.config, args.stage)
    except InputError as error:
        logger.error("Stopped: %s", error)
        return 1
    text, ok = summary(results)
    print(text)
    return 0 if ok else 1


__all__ = [
    "LOADED_AT",
    "ROW_FIELD",
    "TABLES",
    "LocalTableWarehouse",
    "SourceContract",
    "build_pipelines",
    "ingest",
    "source_contracts",
]

if __name__ == "__main__":
    sys.exit(main())
