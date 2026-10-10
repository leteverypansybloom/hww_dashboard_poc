"""Data for the HWW dashboard: load the CSVs made by wrangle.py and do the sums.

This file has no Streamlit code, so the numbers can be tested on their own.
dashboard.py only draws what these functions return.
"""

import os
import re
from collections.abc import Collection, Iterable, Mapping
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

# The CSVs written by wrangle.py. Set HWW_OUTPUT to read another folder (the tests do this).
OUTPUT = Path(os.environ.get("HWW_OUTPUT", Path(__file__).resolve().parent / "output"))
UNKNOWN = "Unknown"

Tables = dict[str, pd.DataFrame]  # table name -> table, as returned by load_tables
Filters = Mapping[str, Collection[str]]  # column -> values to keep

# Tables the dashboard reads, and which of their columns are dates.
DATE_COLUMNS = {
    "dim_employer": [],
    "fact_signup": ["signup_month"],
    "fact_engagement": ["date"],
    "dim_survey_response": ["date"],
    "fact_survey_answer": ["date"],
    "question_catalogue": [],
    "fact_event": ["event_date", "action_date"],
    "badges": ["awarded_date"],
    "dim_date": ["date", "month_start"],
}

# Page 3 metric picker: label on screen -> event_type in fact_engagement, and chart title.
ENGAGEMENT_METRICS = {
    "Website account sign ups": ("account_signup", "Registered HWW website accounts"),
    "Employer survey completions": ("survey_completed", "Employer Survey Tool completions"),
    "WAS requests": ("was_request", "Workplace Advisor Support requests"),
    "WAS completed requests": ("was_completed", "Workplace Advisor Support requests completed"),
}

# Page 4 metric picker: label on screen -> action in fact_event.
EVENT_METRICS = {
    "Signups": "signup",
    "Attendances": "attended",
    "Completed survey": "completed_survey",
}

# Order the filter options the way people expect, not alphabetically. Anything else goes after.
OPTION_ORDER = {
    "sector": ["Public", "Private", "Charity or voluntary", "Other"],
    "size_band": ["0-9", "10-49", "50-249", "250-999", "1000+"],
    "sites_band": ["1", "2-5", "6+", "Not applicable (remote)"],
}


# ---------------------------------------------------------------- loading


def data_stamp(folder: Path | None = None) -> float:
    """Return the latest change time of the output files.

    The dashboard passes this to its cached loader, so the cache is refreshed after
    wrangle.py runs.

    Args:
        folder: Folder of CSVs (defaults to ``OUTPUT``).

    Returns:
        Latest modification time in seconds since 1970, or 0 if there are no CSVs.
    """
    files = list(Path(folder or OUTPUT).glob("*.csv"))
    return max((f.stat().st_mtime for f in files), default=0)


def load_tables(folder: Path | None = None) -> Tables:
    """Read every table the dashboard needs. Blank cells stay as '' and dates become Timestamps.

    Args:
        folder: Folder of CSVs (defaults to ``OUTPUT``).

    Returns:
        Table name -> DataFrame for every table in ``DATE_COLUMNS``.

    Raises:
        FileNotFoundError: A table is missing (wrangle.py has not been run).
    """
    folder = Path(folder or OUTPUT)
    tables = {}
    for name, date_columns in DATE_COLUMNS.items():
        path = folder / f"{name}.csv"
        if not path.exists():
            raise FileNotFoundError(f"{path} not found. Run 'python wrangle.py' first.")
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        for column in date_columns:
            df[column] = pd.to_datetime(df[column], errors="coerce")
        tables[name] = df
    catalogue = tables["question_catalogue"]
    if "answer_order" in catalogue:
        catalogue["answer_order"] = catalogue["answer_order"].astype(int)
    return tables


# ---------------------------------------------------------------- filters


def ordered_options(column: str, *value_lists: Iterable[str]) -> list[str]:
    """List every distinct value seen for a filter, in a sensible order with Unknown last.

    Args:
        column: Filter column, used to look up a preferred order in ``OPTION_ORDER``.
        *value_lists: Values from one or more tables. Blanks are ignored.

    Returns:
        Preferred values first (in ``OPTION_ORDER``), then the rest A-Z, then Unknown.
    """
    values = {v for values in value_lists for v in values if v != ""}
    preferred = [v for v in OPTION_ORDER.get(column, []) if v in values]
    rest = sorted(values - set(preferred) - {UNKNOWN})
    return preferred + rest + ([UNKNOWN] if UNKNOWN in values else [])


def apply_filters(df: pd.DataFrame, filters: Filters) -> pd.DataFrame:
    """Keep rows whose value is among the chosen ones, for every filter.

    Args:
        df: Table with a column for each filter.
        filters: {column: list of allowed values}. An empty list keeps nothing.

    Returns:
        The matching rows.
    """
    keep = pd.Series(True, index=df.index)
    for column, allowed in filters.items():
        keep &= df[column].isin(allowed)
    return df[keep]


def with_employer_attributes(rows: pd.DataFrame, dim_employer: pd.DataFrame) -> pd.DataFrame:
    """Add sector / industry / size / sites from dim_employer. Rows with no employer get Unknown.

    Args:
        rows: Table with an employer_id column ('' when not linked).
        dim_employer: The employer table.

    Returns:
        A new table with the four attribute columns added.
    """
    attributes = dim_employer[["employer_id", "sector", "industry", "size_band", "sites_band"]]
    merged = rows.merge(attributes, on="employer_id", how="left")
    for column in ("sector", "industry", "size_band", "sites_band"):
        merged[column] = merged[column].fillna(UNKNOWN)
    return merged


def natural_key(text: str) -> list[int | str]:
    """Sort key that puts 'Org 2' before 'Org 10'.

    Args:
        text: The text to sort.

    Returns:
        The text split into lower-case words and whole numbers.
    """
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", text)]


# ---------------------------------------------------------------- page 1: survey findings


def survey_question_results(
    tables: Tables, question_id: str, start: date, end: date, filters: Filters
) -> tuple[pd.DataFrame, int]:
    """Work out the Figure 13 numbers for one question.

    respondents = responses (in the date range and filters) that answered this question
    ticks       = those responses that chose the option
    percent     = ticks / respondents * 100
    Every option in the catalogue is returned, including ones nobody chose (0%).

    Args:
        tables: From ``load_tables``.
        question_id: E.g. ``"Q04"``.
        start: First response date to include.
        end: Last response date to include.
        filters: Filters on the response's sector / industry / size_band / sites_band.

    Returns:
        (DataFrame of options, number of respondents). The options have answer_id, answer,
        answer_short, answer_order, question_type, ticks, respondents and percent.
    """
    responses = apply_filters(tables["dim_survey_response"], filters)
    responses = responses[responses["date"].between(pd.Timestamp(start), pd.Timestamp(end))]

    answers = tables["fact_survey_answer"]
    answers = answers[
        (answers["question_id"] == question_id)
        & answers["response_id"].isin(responses["response_id"])
    ]
    respondents = answers["response_id"].nunique()
    ticks = answers.groupby("answer_id")["response_id"].nunique()

    catalogue = tables["question_catalogue"]
    options = catalogue[catalogue["question_id"] == question_id][
        ["answer_id", "answer", "answer_short", "answer_order", "question_type"]
    ].copy()
    options["ticks"] = options["answer_id"].map(ticks).fillna(0).astype(int)
    options["respondents"] = respondents
    options["percent"] = options["ticks"] / respondents * 100 if respondents else 0.0
    return options.reset_index(drop=True), respondents


# ---------------------------------------------------------------- page 2: employer view


def employer_summary(
    tables: Tables, employer_ids: Collection[str], today: date | None = None
) -> dict[str, Any]:
    """Work out the headline numbers for one or more employers.

    Engagement dates after today (e.g. WAS sessions booked in the future) are left out of
    'most recent engagement' and counted in future_events instead.

    Args:
        tables: From ``load_tables``.
        employer_ids: The chosen employers.
        today: Treat this as today (the tests fix it). Defaults to the real date.

    Returns:
        users, survey_responses, was_relationships, peer_relationships (counts);
        first_date / last_date (Timestamp or None) with first_precision / last_precision
        ('day' or 'month'); future_events (count); badges (sorted names).
    """
    now = pd.Timestamp(today or date.today())
    events = tables["fact_engagement"]
    events = events[events["employer_id"].isin(employer_ids)]
    counts = events["event_type"].value_counts()

    dated = events[events["date"].notna()].sort_values("date")
    past = dated[dated["date"] <= now]
    first = past.iloc[0] if len(past) else None
    last = past.iloc[-1] if len(past) else None

    badges = tables["badges"]
    badge_names = sorted(set(badges.loc[badges["employer_id"].isin(employer_ids), "badge"]) - {""})

    return {
        "users": int(counts.get("account_signup", 0)),
        "survey_responses": int(counts.get("survey_completed", 0)),
        "was_relationships": int(counts.get("was_request", 0)),
        "peer_relationships": int(counts.get("peer_mentoring_interest", 0)),
        "first_date": None if first is None else first["date"],
        "first_precision": None if first is None else first["date_precision"],
        "last_date": None if last is None else last["date"],
        "last_precision": None if last is None else last["date_precision"],
        "future_events": int((dated["date"] > now).sum()),
        "badges": badge_names,
    }


def format_long_date(when: pd.Timestamp | None, precision: str | None = "day") -> str:
    """Write a date the way the mockups do.

    Args:
        when: The date (None or NaT for no date).
        precision: 'month' when only the month is known.

    Returns:
        '4th December 2025', 'November 2025' for month precision, or 'Not recorded'.
    """
    if when is None or pd.isna(when):
        return "Not recorded"
    if precision == "month":
        return f"{when:%B %Y}"
    day = when.day
    suffix = "th" if 11 <= day % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix} {when:%B %Y}"


# ---------------------------------------------------------------- page 3: engagement


def monthly_counts(
    tables: Tables, event_type: str, start: date, end: date, filters: Filters
) -> tuple[pd.DataFrame, int]:
    """Count events per month, with a running total, for the months from start to end.

    Months with no events are included as 0, so the bars and the running total are complete.
    The filter works on whole months, because sign-ups are only recorded by month.

    Args:
        tables: From ``load_tables``.
        event_type: An event_type in fact_engagement, e.g. ``"account_signup"``.
        start: Any day in the first month.
        end: Any day in the last month.
        filters: Filters on the employer's sector / industry / sites_band.

    Returns:
        (DataFrame month/count/cumulative, number of matching events with no date).
    """
    events = tables["fact_engagement"]
    events = events[events["event_type"] == event_type]
    events = apply_filters(with_employer_attributes(events, tables["dim_employer"]), filters)
    undated = int(events["date"].isna().sum())

    months = pd.period_range(pd.Timestamp(start), pd.Timestamp(end), freq="M")
    event_months = events["date"].dropna().dt.to_period("M")
    counts = event_months.value_counts().reindex(months, fill_value=0)
    result = pd.DataFrame({"month": months.to_timestamp(), "count": counts.to_numpy()})
    result["cumulative"] = result["count"].cumsum()
    return result, undated


# ---------------------------------------------------------------- page 4: events


def event_counts(tables: Tables, event_names: list[str], action: str) -> pd.DataFrame:
    """Count rows with this action for each chosen event, in the order given.

    Args:
        tables: From ``load_tables``.
        event_names: The chosen events. Events with no rows get 0.
        action: An action in fact_event, e.g. ``"signup"``.

    Returns:
        Columns event_name and count.
    """
    events = tables["fact_event"]
    rows = events[events["event_name"].isin(event_names) & (events["action"] == action)]
    counts = rows.groupby("event_name").size().reindex(event_names, fill_value=0)
    return counts.rename_axis("event_name").reset_index(name="count")
