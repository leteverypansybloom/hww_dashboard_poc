"""Write the WAS dummy workbook as a Microsoft Graph list export.

    python scripts/make_was_jsonl.py

Reads tests/data/inputs/dummy_was_database.xlsx and writes
dummy_was_database.jsonl beside it, one list item per line, in the form
GET /sites/{site}/lists/{list}/items?$expand=fields returns:

- the item's envelope (id, created and modified times and people, web
  address) around a nested fields object;
- fields under SharePoint internal names, not workbook headings;
- SharePoint's own system fields beside the list's columns;
- dates as UTC text, so a UK summer date is 23:00 on the day before;
- a multi-choice column as an array, with its type annotation;
- a person column as a lookup id;
- a blank value left out.

The internal names in COLUMNS follow SharePoint's naming rule: spaces
and symbols encoded, cut to 32 characters, a digit added on a clash.
They are not read from a real list.
"""

import json
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from openpyxl import load_workbook

INPUTS = Path(__file__).resolve().parent.parent / "tests" / "data" / "inputs"
WORKBOOK = INPUTS / "dummy_was_database.xlsx"
EXPORT = INPUTS / "dummy_was_database.jsonl"

SITE_ZONE = ZoneInfo("Europe/London")
TENANT = "https://example.org"
LIST_URL = f"{TENANT}/personal/name_example_org/Lists/WAS%20database"
SITE_ID = "example.org,{site},{web}".format(
    site=uuid5(NAMESPACE_URL, "site"), web=uuid5(NAMESPACE_URL, "web")
)
LIST_ID = str(uuid5(NAMESPACE_URL, "list"))
CREATOR = {
    "user": {
        "email": "name@example.org",
        "id": str(uuid5(NAMESPACE_URL, "user")),
        "displayName": "Jan Job",
    }
}
ADVISER_LOOKUP_ID = "12"

#: Workbook heading -> (internal name, kind of SharePoint column).
#: Item Type and Path come from SharePoint's Excel export. Graph has no
#: such fields: the envelope's contentType and webUrl hold them.
COLUMNS = {
    "Participant ID": ("Participant_x0020_ID", "value"),
    "Date of Enquiry": ("Date_x0020_of_x0020_Enquiry", "date"),
    "Title": ("Title", "value"),
    "Number of employees": ("Number_x0020_of_x0020_employees", "value"),
    "Sector": ("Sector", "value"),
    "Organisation Industry ": ("Organisation_x0020_Industry_x002", "value"),
    "Number of sites": ("Number_x0020_of_x0020_sites", "value"),
    "Have they worked with HWW before?": (
        "Have_x0020_they_x0020_worked_x00",
        "value",
    ),
    "How did they hear of HWW / WAS service?": (
        "How_x0020_did_x0020_they_x0020_h",
        "value",
    ),
    "Key contact ": ("Key_x0020_contact_x0020_", "value"),
    "Job role": ("Job_x0020_role", "value"),
    "Preferred contact details": (
        "Preferred_x0020_contact_x0020_de",
        "value",
    ),
    "Accessibility requirements including language ": (
        "Accessibility_x0020_requirements",
        "value",
    ),
    "Date allocated to adviser": (
        "Date_x0020_allocated_x0020_to_x0",
        "date",
    ),
    "HWW Adviser": ("HWW_x0020_AdviserLookupId", "person"),
    "Date booking request sent to organisation": (
        "Date_x0020_booking_x0020_request",
        "date",
    ),
    "Date of Session 1 ": ("Date_x0020_of_x0020_Session_x002", "date"),
    "Duration of session 1 ": ("Duration_x0020_of_x0020_session_", "value"),
    "Date summary sent to organisation": (
        "Date_x0020_summary_x0020_sent_x0",
        "date",
    ),
    "Topics discussed in session 1": (
        "Topics_x0020_discussed_x0020_in_",
        "choices",
    ),
    "Date of session 2": ("Date_x0020_of_x0020_session_x0020", "date"),
    "Duration of session 2": ("Duration_x0020_of_x0020_session_0", "value"),
    "Date Summary 2 sent ": ("Date_x0020_Summary_x0020_2_x0020", "date"),
    "Topics discussed in session 2": (
        "Topics_x0020_discussed_x0020_in_0",
        "choices",
    ),
    "Date of Session 3 ": ("Date_x0020_of_x0020_Session_x0021", "date"),
}
NOT_IN_GRAPH = {"Item Type", "Path"}


def utc_text(moment: datetime) -> str:
    """Format a time as Graph does.

    Args:
        moment: A time with a time zone.

    Returns:
        UTC text such as 2026-06-30T23:00:00Z.
    """
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def graph_date(day: datetime) -> str:
    """The UTC text SharePoint sends for a date entered at the site.

    Args:
        day: The date as the workbook holds it, at midnight.

    Returns:
        Local midnight at the site, in UTC.
    """
    return utc_text(day.replace(tzinfo=SITE_ZONE))


def list_fields(row: dict[str, Any]) -> dict[str, Any]:
    """The list's own columns for one workbook row.

    Args:
        row: Workbook heading -> cell value.

    Returns:
        Internal name -> value as Graph sends it. Blank values are left
        out, and a multi-choice column gains its type annotation.
    """
    fields: dict[str, Any] = {}
    for heading, (internal, kind) in COLUMNS.items():
        value = row[heading]
        if value is None:
            continue
        if kind == "date":
            fields[internal] = graph_date(value)
        elif kind == "person":
            fields[internal] = ADVISER_LOOKUP_ID
        elif kind == "choices":
            fields[f"{internal}@odata.type"] = "Collection(Edm.String)"
            fields[internal] = value.split(";#")
        else:
            fields[internal] = value
    return fields


def list_item(item_id: int, row: dict[str, Any]) -> dict[str, Any]:
    """One list item as Graph returns it.

    Args:
        item_id: The item's id in the list.
        row: Workbook heading -> cell value.

    Returns:
        The envelope with its nested fields.
    """
    dates = [value for value in row.values() if isinstance(value, datetime)]
    created = utc_text(
        datetime.combine(
            row["Date allocated to adviser"], time(9), tzinfo=SITE_ZONE
        )
    )
    modified = utc_text(datetime.combine(max(dates), time(9), tzinfo=UTC))
    etag = f'"{uuid5(NAMESPACE_URL, f"item{item_id}")},1"'
    return {
        "@odata.etag": etag,
        "createdDateTime": created,
        "eTag": etag,
        "id": str(item_id),
        "lastModifiedDateTime": modified,
        "webUrl": f"{LIST_URL}/{item_id}_.000",
        "createdBy": CREATOR,
        "lastModifiedBy": CREATOR,
        "parentReference": {"id": LIST_ID, "siteId": SITE_ID},
        "contentType": {"id": "0x0100", "name": row["Item Type"]},
        "fields@odata.context": (
            "https://graph.microsoft.com/v1.0/$metadata#sites"
            f"('{SITE_ID}')/lists('{LIST_ID}')/items('{item_id}')"
            "/fields/$entity"
        ),
        "fields": {
            "@odata.etag": etag,
            **list_fields(row),
            "id": str(item_id),
            "ContentType": row["Item Type"],
            "Modified": modified,
            "Created": created,
            "AuthorLookupId": ADVISER_LOOKUP_ID,
            "EditorLookupId": ADVISER_LOOKUP_ID,
            "_UIVersionString": "1.0",
            "Attachments": False,
            "Edit": "",
            "LinkTitleNoMenu": row["Title"],
            "LinkTitle": row["Title"],
            "ItemChildCount": "0",
            "FolderChildCount": "0",
            "_ComplianceFlags": "",
            "_ComplianceTag": "",
            "_ComplianceTagWrittenTime": "",
            "_ComplianceTagUserId": "",
        },
    }


def export_text(workbook: Path = WORKBOOK) -> str:
    """Build the export from the workbook.

    Args:
        workbook: The dummy WAS workbook.

    Returns:
        The file's text: one JSON object per line.

    Raises:
        ValueError: The workbook's headings aren't the expected ones.
    """
    book = load_workbook(workbook)
    rows = book["query"].iter_rows(values_only=True)
    headings = [str(heading) for heading in next(rows)]
    if set(headings) != set(COLUMNS) | NOT_IN_GRAPH:
        raise ValueError("The workbook's headings don't match COLUMNS")
    lines = []
    for item_id, values in enumerate(rows, start=1):
        item = list_item(item_id, dict(zip(headings, values, strict=True)))
        lines.append(json.dumps(item, ensure_ascii=False))
    return "".join(f"{line}\n" for line in lines)


def main() -> None:
    """Write the export beside the workbook."""
    EXPORT.write_text(export_text(), encoding="utf-8", newline="\n")
    print(f"Wrote {EXPORT}")


if __name__ == "__main__":
    main()
