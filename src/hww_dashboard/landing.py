"""Land the HWW workbooks in raw JSON tables with py-common.

This is the ingestion job: ``python ingest.py`` (or
``python -m hww_dashboard.landing``). It runs one py-common
``Pipeline`` per workbook, that is per landing folder:

1. the source lists the workbooks dropped in that folder (a local
   folder, or a prefix in a GCS bucket). The monitoring workbook,
   dropped in ``signups/``, holds two sources' sheets ("Account
   signups" and "Survey info");
2. the workbook is checked against its contract (below): every column
   must be one the contract lists or excludes, and every listed column
   must hold its declared type, or the file is quarantined and nothing
   from it loads;
3. each sheet's loaded columns go into the source's raw table
   (``hww_signups``, ``hww_survey``, ``hww_was``, ``hww_peer``), one
   JSON payload per row with the file, version, sheet and Excel row
   number it came from, with the raw file, the converted rows and an
   audit record kept in the store.

Personal and unused columns are excluded from the raw tables. The
store still archives complete original workbooks, including excluded
columns, for successful and quarantined uploads. ``wrangle.py`` reads
committed loads when ``[landed] read = true`` (see
:mod:`hww_dashboard.landed`).

Rows are only ever inserted: the WAS database has a row with no
Participant ID, so no source has a reliable key, and every upload of
these workbooks is the complete list, so readers take only the newest
load.

Locally, ``LocalRawWarehouse`` stands in for py-common's
``RawJsonWarehouse``: same protocol and rows, NDJSON files in a folder.
"""

import argparse
import json
import logging
import os
import re
import shutil
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from py_common.adapters import LocalObjectStore, LocalSource
from py_common.contract import (
    FILE_EXTENSIONS,
    Column,
    Contract,
    Worksheet,
)
from py_common.errors import ConfigError, ServiceError
from py_common.graph import GraphJsonLinesContract
from py_common.model import Outcome, Result, SourceItem, digest
from py_common.pipeline import Pipeline
from py_common.ports import ObjectStore, Source, Warehouse
from py_common.raw import ROW_FIELDS

from hww_dashboard.logs import (
    close_logging,
    configure_logging,
    log_format,
    new_run_id,
)
from hww_dashboard.wrangle import (
    MAPPING_COLUMNS,
    SOURCES,
    Config,
    InputError,
    clean_text,
    error_location,
    input_file,
    load_config,
    read_csv_text,
    validate_survey_columns,
)

logger = logging.getLogger("hww_dashboard.landing")

#: Raw table for each source.
TABLES = {source: f"hww_{source}" for source in SOURCES}

#: Columns of a raw table row, as py-common's RawJsonWarehouse writes
#: them: the NDJSON fields plus the commit time.
RAW_COLUMNS = (*ROW_FIELDS, "ingested_at")

#: py-common's name for a repeated heading: "Other_2" for the second
#: "Other". pandas, which wrangle.read_sheet follows, says "Other.1".
_PANDAS_REPEAT = re.compile(r"^(?P<base>.*)\.(?P<n>\d+)$")
_BLANK_HEADING = re.compile(r"^col_(?P<letter>[A-Z]+)$")


def _strings(*names: str) -> list[Column]:
    """Declare optional text columns.

    Args:
        *names: The column headings.

    Returns:
        One nullable string column per heading.
    """
    return [Column(name, "string", nullable=True) for name in names]


def _dates(*names: str) -> list[Column]:
    """Declare optional date columns.

    Args:
        *names: The column headings.

    Returns:
        One nullable date column per heading.
    """
    return [Column(name, "date", nullable=True) for name in names]


# Headings are exactly as in the workbooks: py-common matches them
# character for character, trailing spaces included. Sheet names are
# the workbooks' own ("query", "Survey info"), as py-common finds
# sheets by name.

SIGNUPS = Worksheet(
    name="Account signups",
    header_row=2,
    # Site counts mix numbers and bands; the heading remains required.
    column_selection="listed",
    columns=[
        Column("col_B", "date", nullable=True),
        Column("Number of sites", "any", nullable=True),
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

#: The survey's sheet in the monitoring workbook, and its heading row
#: (row 1 holds "Last updated" and the question titles).
SURVEY_SHEET = "Survey info"
SURVEY_HEADER_ROW = 2


@dataclass
class SourceContract:
    """What py-common checks and loads for one source.

    Attributes:
        worksheet: The source's sheet in its workbook's contract.
        table: Raw table the sheet's rows load into.
        names: Heading as py-common reads it -> the heading wrangle.py
            knows it by (trimmed, repeats numbered as pandas does).
    """

    worksheet: Worksheet
    table: str
    names: dict[str, str] = field(default_factory=dict)


@dataclass
class Workbook:
    """One landing folder's workbook: its contract and raw tables.

    Attributes:
        folder: Landing folder, below the landing prefix.
        sources: The sources whose sheets it holds, in SOURCES order.
        contract: Checks every one of those sheets.
        tables: Sheet name -> raw table.
    """

    folder: str
    sources: list[str]
    contract: Contract
    tables: dict[str, str]


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
    maps: Path,
    keep_other_text: bool,
    personal_columns: Sequence[str] = (),
) -> tuple[Worksheet, dict[str, str]]:
    """The Survey info contract, from mappings/survey_columns.csv.

    The column map lists every column of the sheet with its role, so
    the contract follows it: role columns and answers are loaded, the
    rest (personal, unused) excluded. "Other (more info)" free text
    loads only when keep_other_free_text is on. The sites column holds
    numbers and text (1, "2-5"), so it is loaded untyped, as on
    Account signups.

    Args:
        maps: The mappings folder.
        keep_other_text: The survey's keep_other_free_text setting.
        personal_columns: Additional headings that must use the drop role.

    Returns:
        The worksheet, and py-common name -> wrangle.py name for each
        loaded column.
    """
    table = read_csv_text(
        maps / "survey_columns.csv", MAPPING_COLUMNS["survey_columns"]
    )
    validate_survey_columns(table)
    personal = {
        clean_text(name).casefold()
        for name in (
            "Name",
            "First Name",
            "Last Name",
            "Email address",
            "Email",
            "Phone",
            "Telephone",
            "Contact details",
            *personal_columns,
        )
    }
    selected = table["column"].map(
        lambda name: clean_text(name).casefold() in personal
    ) & table["role"].ne("drop")
    if selected.any():
        raise InputError(
            "mappings/survey_columns.csv: personal columns must use "
            "the drop role."
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
        if role == "sites":
            columns.append(Column(name, "any", nullable=True))
        else:
            columns.append(
                Column(name, data_types.get(role, "string"), nullable=True)
            )
        names[name] = heading
    worksheet = Worksheet(
        name=SURVEY_SHEET,
        header_row=SURVEY_HEADER_ROW,
        column_selection="listed",
        columns=columns,
        excluded=excluded,
        on_mismatch="quarantine",
    )
    return worksheet, names


def source_contracts(cfg: Config, maps: Path) -> dict[str, SourceContract]:
    """Every source's sheet contract.

    Args:
        cfg: The checked config.
        maps: The mappings folder.

    Returns:
        SourceContract per source, in SOURCES order.
    """
    survey, survey_names = survey_worksheet(
        maps,
        bool(cfg["survey"]["keep_other_free_text"]),
        cfg.get("privacy", {}).get("personal_columns", []),
    )
    sheets = {"signups": SIGNUPS, "survey": survey, "was": WAS, "peer": PEER}
    result: dict[str, SourceContract] = {}
    for source in SOURCES:
        sheet = replace(
            sheets[source],
            allow_empty=cfg[source].get("allow_empty", False),
            header_row=(
                1
                if str(cfg[source].get("file", ""))
                .lower()
                .endswith((".jsonl", ".ndjson"))
                else sheets[source].header_row
            ),
        )
        if source == "survey":
            names = survey_names
        else:
            names = {c.name: pandas_name(c.name) for c in sheet.columns}
        result[source] = SourceContract(sheet, TABLES[source], names)
    return result


def _multi_value_separators(
    section: Mapping[str, Any], worksheet: Worksheet
) -> dict[str, str]:
    """The text columns a Graph list sends as lists of choices.

    A workbook export separates a multi-choice column's values with
    topic_separator, so joining Graph's lists the same way gives the
    pipeline and the Dataform models one form to read.

    Args:
        section: The source's config section.
        worksheet: The source's contract worksheet.

    Returns:
        Canonical heading -> separator.
    """
    separator = section.get("topic_separator")
    if not separator:
        return {}
    text_columns = {
        column.name
        for column in worksheet.columns
        if column.data_type == "string"
    }
    topics = {str(s.get("topics")) for s in section.get("sessions", [])}
    return {name: str(separator) for name in topics & text_columns}


def workbooks(cfg: Config, maps: Path) -> dict[str, Workbook]:
    """The workbook each landing folder receives, with its contract.

    Sources whose ``file`` names the same workbook share a folder
    (landing_folders()), so their sheets share one contract and one
    pipeline: an upload loads all of them, or none if any sheet fails
    its checks. A workbook must arrive under the name its ``file``
    gives.

    Args:
        cfg: The checked config.
        maps: The mappings folder.

    Returns:
        Workbook per landing folder, in SOURCES order.

    Raises:
        InputError: Two sources sharing a workbook read the same sheet.
    """
    contracts = source_contracts(cfg, maps)
    grouped: dict[str, list[str]] = {}
    for source, folder in landing_folders(cfg).items():
        grouped.setdefault(folder, []).append(source)
    result: dict[str, Workbook] = {}
    for folder, sources in grouped.items():
        sheets = [contracts[source].worksheet for source in sources]
        if len({sheet.name for sheet in sheets}) != len(sheets):
            raise InputError(
                f"{', '.join(sources)} read the same sheet of one workbook; "
                "give each source its own sheet."
            )
        first = cfg[sources[0]]
        file_name = str(first["file"])
        json_lines = file_name.lower().endswith((".jsonl", ".ndjson"))
        contract: Contract
        if json_lines:
            canonical = replace(
                sheets[0],
                header_row=1,
                column_selection="listed",
                columns=[
                    (
                        replace(column, data_type="any")
                        if column.data_type == "integer"
                        else column
                    )
                    for column in sheets[0].columns
                ],
                excluded=[],
            )
            try:
                contract = GraphJsonLinesContract(
                    worksheets=[canonical],
                    file_name=file_name,
                    file_format="jsonl",
                    field_map=first.get("field_map", {}),
                    metadata_map=first.get("metadata_map", {}),
                    excluded_fields=first.get("excluded_fields", []),
                    site_time_zone=str(first.get("site_time_zone", "")),
                    multi_value_separators=_multi_value_separators(
                        first, canonical
                    ),
                )
            except ConfigError:
                raise InputError(
                    f"[{sources[0]}]: configure Graph field_map, metadata_map "
                    "and excluded_fields from the migrated list's column "
                    "definitions, and site_time_zone from its regional "
                    "settings, before ingesting JSON Lines."
                ) from None
        else:
            contract = Contract(
                worksheets=sheets,
                file_name=file_name,
            )
        tables = {
            contracts[s].worksheet.name: contracts[s].table for s in sources
        }
        result[folder] = Workbook(folder, sources, contract, tables)
    return result


# ------------------------------------------------ local warehouse


def load_name(key: str, version: str) -> str:
    """The file name a local load is kept under, without its suffix.

    Args:
        key: py-common's load key.
        version: The upload's source version.

    Returns:
        16 hex digits, the same for every retry of the upload.
    """
    return digest(f"{key}\n{version}".encode())[:16]


def local_audit(folder: Path, table: str) -> list[dict[str, Any]]:
    """The committed loads of a local raw table, oldest first.

    Args:
        folder: The tables folder.
        table: Table name, e.g. "hww_was".

    Returns:
        One audit record per committed load.
    """
    path = folder / table
    if not path.is_dir():
        return []
    records = [
        json.loads(record.read_text(encoding="utf-8"))
        for record in path.glob("*.audit.json")
    ]
    return sorted(records, key=lambda record: str(record["timestamp"]))


def local_rows(
    folder: Path, table: str, record: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """The rows of one committed local load.

    Args:
        folder: The tables folder.
        table: Table name.
        record: The load's audit record, from local_audit().

    Returns:
        The rows, each with the columns in RAW_COLUMNS.
    """
    name = load_name(str(record["filename"]), str(record["source_version"]))
    text = (folder / table / f"{name}.ndjson").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.split("\n") if line.strip()]


def _replace(path: Path, data: bytes) -> None:
    """Write a file whole, or leave it as it was.

    Args:
        path: The file.
        data: Its new contents.
    """
    temporary = path.with_name(f"{path.name}.tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class LocalRawWarehouse:
    """py-common Warehouse that keeps raw tables as NDJSON files.

    Stands in for ``RawJsonWarehouse`` on a laptop, with the same
    rules: one raw table per sheet, the same columns (RAW_COLUMNS),
    rows only ever inserted, and each upload loaded once per table.
    Each load of a table is a rows file and an audit record in
    ``<folder>/<table>/``. The audit record is written last, in one
    atomic replace, and is what makes the load committed: rows without
    one are never read, and a retry writes them again.

    Attributes:
        folder: Folder holding one subfolder per table.
        tables: Sheet name -> raw table name.
    """

    def __init__(self, folder: Path | str, tables: Mapping[str, str]) -> None:
        """Point at the tables in a folder (created when first loaded).

        Args:
            folder: Folder for the tables.
            tables: Raw table name for each sheet the pipeline loads.

        Raises:
            ValueError: No tables given, or two sheets share a table.
        """
        if not tables:
            raise ValueError("LocalRawWarehouse needs at least one table")
        if len(set(tables.values())) != len(tables):
            raise ValueError(
                f"Each sheet needs its own raw table, got {dict(tables)!r}"
            )
        self.folder = Path(folder)
        self.tables = dict(tables)

    @property
    def identity(self) -> str:
        """Identifier like RawJsonWarehouse's project.dataset.tables.

        py-common puts it in storage keys and the lock name, so it must
        be a plain name: no drive letter, colon or slash.
        """
        names = "+".join(sorted(self.tables.values()))
        return f"local.{self.folder.resolve().name}.{names}"

    def load(
        self,
        key: str,
        checksum: str,
        data: bytes,
        rows: int,
        item: SourceItem,
    ) -> bool:
        """Insert one file's rows into each sheet's table, once.

        Args:
            key: Load key (source identity and checksum).
            checksum: SHA-256 of the source file.
            data: NDJSON from py_common.raw.to_ndjson().
            rows: Expected row count across all sheets.
            item: Source file the rows came from.

        Returns:
            True if any table was written, False if every table
            already has this upload.

        Raises:
            ValueError: A row is not raw JSON, names a sheet with no
                table, or the row count differs (as RawJsonWarehouse).
            ServiceError: The folder can't be written.
        """
        by_sheet: dict[str, list[dict[str, Any]]] = {}
        for number, line in enumerate(data.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                sheet = row["sheet_name"]
            except (ValueError, KeyError, TypeError) as error:
                raise ValueError(
                    f"Line {number} is not a raw JSON row: {error}"
                ) from error
            by_sheet.setdefault(sheet, []).append(row)
        unknown = sorted(set(by_sheet) - set(self.tables))
        if unknown:
            raise ValueError(
                f"No raw table configured for sheet(s) "
                f"{', '.join(unknown)} in {key}"
            )
        total = sum(len(sheet_rows) for sheet_rows in by_sheet.values())
        if total != rows:
            raise ValueError(
                f"Row count mismatch: expected {rows}, got {total}"
            )
        timestamp = datetime.now(UTC)
        earlier = [
            datetime.fromisoformat(record["timestamp"])
            for table in self.tables.values()
            for record in local_audit(self.folder, table)
        ]
        if earlier and timestamp <= max(earlier):
            timestamp = max(earlier) + timedelta(microseconds=1)
        written = False
        for sheet, table in self.tables.items():
            if self._committed(table, key, item.version):
                continue
            self._commit(
                table, key, checksum, item, by_sheet.get(sheet, []), timestamp
            )
            written = True
        return written

    def _committed(self, table: str, key: str, version: str) -> bool:
        """Whether this upload is already in a table.

        Args:
            table: Table name.
            key: Load key.
            version: Source version of the upload.

        Returns:
            True if the table has a LOADED audit record for it.
        """
        path = self.folder / table / f"{load_name(key, version)}.audit.json"
        if not path.exists():
            return False
        record = json.loads(path.read_text(encoding="utf-8"))
        return bool(record.get("outcome") == Outcome.LOADED.value.upper())

    def _commit(
        self,
        table: str,
        key: str,
        checksum: str,
        item: SourceItem,
        rows: list[dict[str, Any]],
        timestamp: datetime,
    ) -> None:
        """Write one table's rows, then the audit record that commits them.

        Args:
            table: Table name.
            key: Load key.
            checksum: SHA-256 of the source file.
            item: Source file the rows came from.
            rows: The sheet's rows, from the NDJSON.
            timestamp: The load's commit time, shared by every table.

        Raises:
            ServiceError: The folder can't be written.
        """
        folder = self.folder / table
        name = load_name(key, item.version)
        stamp = timestamp.isoformat()
        lines = [
            json.dumps(
                {**row, "ingested_at": stamp},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            for row in rows
        ]
        record = {
            "filename": key,
            "checksum": checksum,
            "destination": table,
            "source_version": item.version,
            "source_file": item.name,
            "row_count": len(rows),
            "outcome": Outcome.LOADED.value.upper(),
            "timestamp": stamp,
        }
        try:
            folder.mkdir(parents=True, exist_ok=True)
            _replace(
                folder / f"{name}.ndjson",
                "".join(f"{line}\n" for line in lines).encode("utf-8"),
            )
            _replace(
                folder / f"{name}.audit.json",
                json.dumps(record, sort_keys=True).encode("utf-8"),
            )
        except OSError as error:
            raise ServiceError(
                f"{table}: cannot write {folder} ({error})"
            ) from error


# ------------------------------------------------ the job


@dataclass
class LandingSettings:
    """Where the job reads, keeps and loads, from [landed] in config.

    Attributes:
        target: "local" (folders) or "gcp" (buckets and BigQuery).
        landing: Local: folder with one subfolder per source.
        store: Local: folder for kept copies and audit records.
        tables: Local: folder for the raw tables.
        project: GCP project.
        landing_bucket: GCS bucket the workbooks are dropped in.
        landing_prefix: Folder in that bucket; sources are below it.
        store_bucket: GCS bucket for kept copies and audit records.
        dataset: BigQuery dataset for the raw tables.
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


def landing_folders(cfg: Config) -> dict[str, str]:
    """The landing folder each source reads, below the landing prefix.

    Sources whose ``file`` names the same workbook share the folder of
    the first of them in SOURCES order, so one upload loads each: the
    monitoring workbook feeds signups and survey, which both read
    ``signups``. Every other source reads a folder named after itself.

    Args:
        cfg: The checked config.

    Returns:
        Folder per source, in SOURCES order.
    """
    first: dict[str, str] = {}
    folders: dict[str, str] = {}
    for source in SOURCES:
        name = str(cfg[source]["file"])
        folders[source] = first.setdefault(name, source)
    return folders


def build_pipelines(
    cfg: Config, maps: Path, settings: LandingSettings
) -> dict[str, Pipeline]:
    """One py-common Pipeline per workbook.

    Args:
        cfg: The checked config.
        maps: The mappings folder.
        settings: From landing_settings().

    Returns:
        Pipeline per landing folder, in SOURCES order.
    """
    store: ObjectStore
    if settings.target == "gcp":
        from py_common.adapters.bigquery_raw import RawJsonWarehouse
        from py_common.adapters.gcs import GCSObjectStore, GCSSource

        store = GCSObjectStore(settings.project, settings.store_bucket)
    else:
        store = LocalObjectStore(long_path(settings.store))
    pipelines: dict[str, Pipeline] = {}
    for folder, book in workbooks(cfg, maps).items():
        files: Source
        warehouse: Warehouse
        if settings.target == "gcp":
            prefix = "/".join(
                p for p in (settings.landing_prefix, folder) if p
            )
            files = GCSSource(
                settings.project,
                settings.landing_bucket,
                prefix,
                extensions=FILE_EXTENSIONS[book.contract.file_format],
            )
            warehouse = RawJsonWarehouse(
                settings.project, settings.dataset, book.tables
            )
        else:
            files = LocalSource(
                settings.landing / folder,
                extensions=FILE_EXTENSIONS[book.contract.file_format],
            )
            warehouse = LocalRawWarehouse(settings.tables, book.tables)
        pipelines[folder] = Pipeline(
            source=files,
            store=store,
            warehouse=warehouse,
            contract=book.contract,
        )
    return pipelines


def stage(cfg: Config, inputs: Path, landing: Path) -> list[Path]:
    """Copy each source's workbook from a folder into its landing folder.

    The local stand-in for dropping the files in the landing bucket:
    the files the config names are copied to their landing folders. A
    workbook that feeds several sources is copied once.

    Args:
        cfg: The checked config.
        inputs: Folder holding the workbooks.
        landing: Landing folder.

    Returns:
        The copies made.
    """
    labels = {
        "signups": "Account signups",
        "survey": "Survey info",
        "was": "WAS database",
        "peer": "Peer mentoring",
    }
    folders = landing_folders(cfg)
    copies: list[Path] = []
    for source in SOURCES:
        path = input_file(inputs, cfg[source], labels[source])
        target = landing / folders[source] / path.name
        if target in copies:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copies.append(target)
    return copies


def ingest(
    config_path: str | Path, stage_from: Path | None = None
) -> dict[str, list[Result]]:
    """Run every workbook's py-common pipeline.

    Args:
        config_path: config.toml.
        stage_from: Folder to copy the workbooks from into the local
            landing folder first (local target only).

    Returns:
        Each landing folder's py-common Results, one per file seen.

    Raises:
        InputError: The config is invalid, staging was asked for with
            the GCP target, or the raw load health checks failed.
        Exception: The first unexpected error from a pipeline (another
            run holding its lock, a service failing, a bug), once every
            folder has been tried.
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
    first_error: Exception | None = None
    for folder, pipeline in build_pipelines(cfg, maps, settings).items():
        try:
            results[folder] = pipeline.run()
        except Exception as error:
            # One folder's failure must not stop the others loading.
            logger.exception(
                "Ingestion could not finish for %s (%s); carrying on with "
                "the other folders.",
                folder,
                type(error).__name__,
            )
            first_error = first_error or error
    if first_error is not None:
        raise first_error
    if settings.target == "gcp":
        from google.cloud import bigquery
        from py_common.runner import check_duplicate_loads, check_freshness

        client = bigquery.Client(project=settings.project)
        duplicates = check_duplicate_loads(
            client, f"{settings.project}.{settings.dataset}.audit"
        )
        freshness_view = cfg.get("checks", {}).get("freshness_view")
        overdue = (
            check_freshness(client, freshness_view) if freshness_view else []
        )
        if duplicates or overdue:
            raise InputError(
                "Raw load health checks failed; publication is held."
            )
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
    for folder, folder_results in results.items():
        if not folder_results:
            lines.append(f"{folder}: no files in its landing folder")
            ok = False
        for result in folder_results:
            line = (
                f"{folder}: {result.item.name}: {result.outcome.value}, "
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
        0 if every file loaded or was already loaded; 1 if a file was
        quarantined or failed, a source folder was empty, or the config
        needs fixing; 2 for anything unexpected (another run holding
        the lock, a cloud service failing to list the files, a bug),
        logged with its traceback.
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
    try:
        mode = log_format()
    except ValueError as error:
        print(f"Stopped: {error}", file=sys.stderr)
        return 1
    # The project's own log setup, so HWW_LOG_FORMAT=json gives Cloud
    # Logging structured lines. py-common logs under its own name, so
    # its lines get the same handlers.
    handlers = configure_logging(new_run_id(), mode)
    library = logging.getLogger("py_common")
    library.setLevel(logging.INFO)
    for handler in handlers:
        library.addHandler(handler)
    try:
        try:
            results = ingest(args.config, args.stage)
        except InputError as error:
            logger.error("Stopped: %s", error)
            return 1
        except Exception as error:
            logger.exception(
                "Unexpected error (%s at %s). This is a bug, or a service "
                "or another run got in the way: see the traceback.",
                type(error).__name__,
                error_location(error),
            )
            return 2
        text, ok = summary(results)
        for line in text.split("\n"):
            logger.info("%s", line)
        if not ok:
            logger.error(
                "Ingestion did not load every file; see the lines above."
            )
        return 0 if ok else 1
    finally:
        for handler in handlers:
            library.removeHandler(handler)
        close_logging(handlers)


__all__ = [
    "RAW_COLUMNS",
    "TABLES",
    "LocalRawWarehouse",
    "SourceContract",
    "Workbook",
    "build_pipelines",
    "ingest",
    "landing_folders",
    "local_audit",
    "local_rows",
    "source_contracts",
    "workbooks",
]

if __name__ == "__main__":
    sys.exit(main())
