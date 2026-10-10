"""Data for the HWW dashboard: load the CSVs made by wrangle.py and do the sums.

This file has no Streamlit code, so the numbers can be tested on their own.
dashboard.py only draws what these functions return.
"""

import os
import re
from datetime import date
from pathlib import Path

import pandas as pd

# The CSVs written by wrangle.py. Set HWW_OUTPUT to read another folder (the tests do this).
OUTPUT = Path(os.environ.get("HWW_OUTPUT", Path(__file__).resolve().parent / "output"))
UNKNOWN = "Unknown"

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
EVENT_METRICS = {"Signups": "signup", "Attendances": "attended", "Completed survey": "completed_survey"}

# Order the filter options the way people expect, not alphabetically. Anything else goes after.
OPTION_ORDER = {
    "sector": ["Public", "Private", "Charity or voluntary", "Other"],
    "size_band": ["0-9", "10-49", "50-249", "250-999", "1000+"],
    "sites_band": ["1", "2-5", "6+", "Not applicable (remote)"],
}


# ---------------------------------------------------------------- loading


def data_stamp(folder=None):
    """Latest change time of the output files. Used so the dashboard reloads after wrangle.py runs."""
    files = list(Path(folder or OUTPUT).glob("*.csv"))
    return max((f.stat().st_mtime for f in files), default=0)


def load_tables(folder=None):
    """Read every table the dashboard needs. Blank cells stay as '' and dates become Timestamps."""
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
    if "answer_order" in tables["question_catalogue"]:
        tables["question_catalogue"]["answer_order"] = tables["question_catalogue"]["answer_order"].astype(int)
    return tables


# ---------------------------------------------------------------- filters


def ordered_options(column, *value_lists):
    """Every distinct value seen for a filter, in a sensible order with Unknown last."""
    values = {v for values in value_lists for v in values if v != ""}
    preferred = [v for v in OPTION_ORDER.get(column, []) if v in values]
    rest = sorted(values - set(preferred) - {UNKNOWN})
    return preferred + rest + ([UNKNOWN] if UNKNOWN in values else [])


def apply_filters(df, filters):
    """Keep rows whose value is among the chosen ones, for every filter.

    filters: {column: list of allowed values}. An empty list keeps nothing.
    """
    keep = pd.Series(True, index=df.index)
    for column, allowed in filters.items():
        keep &= df[column].isin(allowed)
    return df[keep]


def with_employer_attributes(rows, dim_employer):
    """Add sector / industry / size / sites from dim_employer. Rows with no employer get Unknown."""
    attributes = dim_employer[["employer_id", "sector", "industry", "size_band", "sites_band"]]
    merged = rows.merge(attributes, on="employer_id", how="left")
    for column in ("sector", "industry", "size_band", "sites_band"):
        merged[column] = merged[column].fillna(UNKNOWN)
    return merged


def natural_key(text):
    """Sort 'Org 2' before 'Org 10'."""
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", text)]


# ---------------------------------------------------------------- page 1: survey findings


def survey_question_results(tables, question_id, start, end, filters):
    """Figure 13 numbers for one question.

    respondents = responses (in the date range and filters) that answered this question
    ticks       = those responses that chose the option
    percent     = ticks / respondents * 100
    Every option in the catalogue is returned, including ones nobody chose (0%).
    Returns (DataFrame of options, number of respondents).
    """
    responses = apply_filters(tables["dim_survey_response"], filters)
    responses = responses[responses["date"].between(pd.Timestamp(start), pd.Timestamp(end))]

    answers = tables["fact_survey_answer"]
    answers = answers[(answers["question_id"] == question_id) & answers["response_id"].isin(responses["response_id"])]
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


def employer_summary(tables, employer_ids, today=None):
    """Headline numbers for one or more employers.

    Engagement dates after today (e.g. WAS sessions booked in the future) are left out of
    'most recent engagement' and counted in future_events instead.
    """
    today = pd.Timestamp(today or date.today())
    events = tables["fact_engagement"]
    events = events[events["employer_id"].isin(employer_ids)]
    counts = events["event_type"].value_counts()

    dated = events[events["date"].notna()].sort_values("date")
    past = dated[dated["date"] <= today]
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
        "future_events": int((dated["date"] > today).sum()),
        "badges": badge_names,
    }


def format_long_date(when, precision="day"):
    """'4th December 2025', or 'November 2025' when only the month is known."""
    if when is None or pd.isna(when):
        return "Not recorded"
    if precision == "month":
        return f"{when:%B %Y}"
    day = when.day
    suffix = "th" if 11 <= day % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix} {when:%B %Y}"


# ---------------------------------------------------------------- page 3: engagement


def monthly_counts(tables, event_type, start, end, filters):
    """Events per month plus a running total, for the months from start to end.

    Months with no events are included as 0, so the bars and the running total are complete.
    The filter works on whole months, because sign-ups are only recorded by month.
    Returns (DataFrame month/count/cumulative, number of matching events with no date).
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


def event_counts(tables, event_names, action):
    """Number of rows with this action for each chosen event, in the order given."""
    events = tables["fact_event"]
    rows = events[events["event_name"].isin(event_names) & (events["action"] == action)]
    counts = rows.groupby("event_name").size().reindex(event_names, fill_value=0)
    return counts.rename_axis("event_name").reset_index(name="count")
