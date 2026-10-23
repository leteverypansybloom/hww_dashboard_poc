"""Build the scenario workbooks: three tiny inputs chosen to test the rules.

    python tests/scenarios/workbooks.py OUT_FOLDER

writes them to OUT_FOLDER, for example to land them through py-common
when checking the Dataform models. The tests build them in a temporary
folder instead. Each row is there to exercise a rule in
docs/rules.md, and README.md in this folder says which. The expected
tables in expected/ were worked out by hand from those rules, not
copied from the pipeline's output.

The file and sheet names, heading rows and column headings are those
of tests/data/config.toml.
"""

import sys
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook

#: The one organisation override the scenario adds to the mappings.
OVERRIDE = ("Delta Trading", "Gamma Group")

SIGNUPS_HEADINGS: list[object] = [
    None,
    None,
    "Org (duplicates in red)",
    "Role (complete if duplicate org)",
    "Size",
    "Sector",
    "Industry",
    "Number of sites",
    "Completed survey?",
    "Requested WAS?",
]
SIGNUPS: list[list[object]] = [
    # The month is in column B, on the first row of each month only.
    [
        None,
        date(2025, 11, 1),
        "Alpha Ltd",
        None,
        "10-49",
        "Private",
        "Education",
        "1",
        "Y (Dec)",
        None,
    ],
    [
        None,
        None,
        "ALPHA LTD",
        "Manager",
        "50-249",
        "Public",
        "Education",
        "2-5",
        None,
        "Y",
    ],
    [
        None,
        date(2025, 12, 1),
        "Beta Café",
        None,
        "0-9",
        "Charity or voluntary",
        "Other",
        "1",
        None,
        None,
    ],
    [
        None,
        None,
        "Gamma Group",
        None,
        "1000+",
        "Other",
        "Construction",
        "6+",
        "N",
        "Y (Jan 26)",
    ],
    # A row with no organisation is dropped.
    [None, None, None, None, None, None, None, None, None, None],
]

Q13 = "Does your organisation offer flexible working arrangements?"
Q14 = (
    "Do employees have regular opportunities to provide feedback on "
    "organisational changes?"
)
SURVEY_HEADINGS: list[object] = [
    "Count",
    "Month",
    "Entry Date",
    "Organisation",
    "Email address",
    "Size",
    "Sector",
    "Industry",
    "Number of sites",
    Q13,
    Q14,
    "Fatigue or burnout",
    "Headaches and migraines",
    "Other",
    # The free-text box after the tick boxes.
    "Other (more info)",
]
SURVEY: list[list[object]] = [
    [
        101,
        date(2026, 1, 1),
        datetime(2026, 1, 10, 9, 30),
        "Alpha Ltd",
        "alpha@example.org",
        "10-49",
        "Private",
        "Education",
        1,
        "Yes, widely available",
        "Weithiau",
        "Fatigue or burnout",
        # An unticked box holding a space.
        " ",
        "Other",
        "Free text, never output",
    ],
    [
        102,
        date(2026, 2, 1),
        datetime(2026, 2, 20, 14, 5, 12),
        "beta café",
        None,
        None,
        None,
        None,
        None,
        "In some teams",
        "Maybe",
        "x",
        "x",
        # An unticked box holding a non-breaking space.
        "\xa0",
        None,
    ],
    [
        103,
        date(2026, 3, 1),
        datetime(2026, 3, 5, 11, 0),
        None,
        None,
        "0-9",
        "Public",
        "other_options",
        "1",
        None,
        "No",
        None,
        None,
        None,
        None,
    ],
    # A repeated Count: only the first row counts.
    [
        101,
        None,
        datetime(2026, 1, 11, 8, 0),
        "Alpha Ltd",
        "alpha@example.org",
        "10-49",
        "Private",
        "Education",
        1,
        "Rarely or not at all",
        "No",
        None,
        None,
        None,
        None,
    ],
    # No Count: dropped.
    [
        None,
        None,
        datetime(2026, 3, 6, 10, 0),
        "Gamma Group",
        None,
        "1000+",
        "Public",
        "Construction",
        "6+",
        "Yes, widely available",
        "Yes",
        "Fatigue or burnout",
        None,
        None,
        None,
    ],
]

WAS_HEADINGS: list[object] = [
    "Participant ID",
    "Title",
    "Date of Enquiry",
    "Date allocated to adviser",
    "Number of employees",
    "Sector",
    "Organisation Industry",
    "Number of sites",
    "Date of Session 1",
    "Duration of session 1",
    "Date summary sent to organisation",
    "Topics discussed in session 1",
    "Date of session 2",
    "Duration of session 2",
    "Date Summary 2 sent",
    "Topics discussed in session 2",
    "Date of Session 3",
]
WAS: list[list[object]] = [
    [
        "1",
        "Alpha Ltd",
        date(2026, 1, 5),
        date(2026, 1, 6),
        "50-250",
        "Private Sector",
        "Education",
        "2",
        date(2026, 1, 20),
        "Under 90 mins",
        date(2026, 1, 27),
        "Physical activity ;#Mental health and wellbeing",
        date(2026, 2, 15),
        "Under 90 minutes",
        date(2026, 2, 20),
        "Physical activity",
        date(2026, 3, 10),
    ],
    # No enquiry date: the allocation date is used. Renamed by the
    # override. Session 1 has a duration but no date.
    [
        "2",
        "Delta Trading",
        None,
        date(2026, 2, 1),
        "1000+",
        "Public",
        "Construction",
        "6-10",
        None,
        "Under 90 minutes",
        None,
        None,
        None,
        None,
        None,
        None,
        None,
    ],
    # No Participant ID: the id is made from the Excel row (4).
    [
        None,
        "Epsilon Works",
        date(2026, 3, 1),
        None,
        "10-19",
        "Other",
        "Education",
        "1",
        date(2026, 3, 15),
        None,
        None,
        "Sleep hygiene",
        None,
        None,
        None,
        None,
        None,
    ],
]

PEER_HEADINGS: list[object] = [
    "Participant ID",
    "Business Name",
    "Date of expression of interest",
    "Business Size",
    "Sector",
    "Industry",
]
PEER: list[list[object]] = [
    # The accent typed as a letter plus a combining mark.
    ["0007", "Beta Café", date(2026, 2, 1), "0-9", "Private", "Other"],
    ["0008", "Alpha Ltd", date(2026, 4, 1), "250-999", "Private", "Education"],
]

#: Each workbook's sheets and their rows. The monitoring workbook holds
#: both Account signups and Survey info.
FILES: dict[str, list[tuple[str, list[list[object]]]]] = {
    "dummy_HWW monitoring and reporting.xlsx": [
        (
            "Account signups",
            [["Synthetic account signups"], SIGNUPS_HEADINGS, *SIGNUPS],
        ),
        (
            "Survey info",
            [["Last updated: 06/03/2026"], SURVEY_HEADINGS, *SURVEY],
        ),
    ],
    "dummy_was_database.xlsx": [("query", [WAS_HEADINGS, *WAS])],
    "dummy_peer_montoring.xlsx": [("query (1)", [PEER_HEADINGS, *PEER])],
}


def write(folder: Path) -> list[Path]:
    """Write the three scenario workbooks.

    Args:
        folder: Where to write them (created if needed).

    Returns:
        The files written.
    """
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for name, sheets in FILES.items():
        book = Workbook()
        book.properties.creator = "HWW scenario builder"
        book.properties.created = datetime(2026, 10, 18)
        book.properties.modified = datetime(2026, 10, 18)
        default = book.active
        assert default is not None
        book.remove(default)
        for sheet, rows in sheets:
            worksheet = book.create_sheet(sheet)
            for row in rows:
                worksheet.append(row)
        path = folder / name
        book.save(path)
        written.append(path)
    return written


if __name__ == "__main__":
    for written_path in write(Path(sys.argv[1])):
        print(written_path)
