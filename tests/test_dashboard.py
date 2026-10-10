"""Checks on the dashboard numbers and pages. Run with: python -m pytest."""

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import dashboard_data as dd
import wrangle

T = pd.Timestamp


def tables_for_tests() -> dd.Tables:
    """A tiny made-up set of tables, so the expected numbers can be worked out by hand."""
    dim_employer = pd.DataFrame(
        {
            "employer_id": ["E1", "E2"],
            "employer_name": ["Org 1", "Org 2"],
            "sector": ["Public", "Private"],
            "industry": ["Education", "Retail"],
            "size_band": ["1000+", "0-9"],
            "sites_band": ["6+", "1"],
        }
    )
    responses = pd.DataFrame(
        {
            "response_id": ["R1", "R2", "R3", "R4"],
            "employer_id": ["E1", "E2", "E1", ""],
            "date": [T("2026-01-10"), T("2026-02-10"), T("2026-03-10"), T("2026-03-11")],
            "sector": ["Public", "Private", "Public", "Unknown"],
            "industry": ["Education", "Retail", "Education", "Unknown"],
            "size_band": ["1000+", "0-9", "1000+", "Unknown"],
            "sites_band": ["6+", "1", "6+", "Unknown"],
        }
    )
    # Q04: R1 ticks A and B, R2 ticks A, R3 ticks B. R4 does not answer Q04.
    answers = pd.DataFrame(
        {
            "response_id": ["R1", "R1", "R2", "R3", "R4"],
            "question_id": ["Q04", "Q04", "Q04", "Q04", "Q01"],
            "answer_id": ["Q04-01", "Q04-02", "Q04-01", "Q04-02", "Q01-01"],
        }
    )
    catalogue = pd.DataFrame(
        {
            "question_id": ["Q04", "Q04", "Q04", "Q01"],
            "answer_id": ["Q04-01", "Q04-02", "Q04-03", "Q01-01"],
            "answer": ["A", "B", "C", "Yes"],
            "answer_short": ["A", "B", "C", "Yes"],
            "answer_order": [1, 2, 3, 1],
            "question_type": ["multi", "multi", "multi", "single"],
        }
    )
    engagement = pd.DataFrame(
        {
            "employer_id": ["E1", "E1", "E2", "E1", "", "E1"],
            "date": [
                T("2025-11-01"),
                T("2026-01-01"),
                T("2026-01-01"),
                T("2026-02-15"),
                T("2026-01-20"),
                T("2030-01-01"),
            ],
            "date_precision": ["month", "month", "month", "day", "day", "day"],
            "event_type": [
                "account_signup",
                "account_signup",
                "account_signup",
                "was_request",
                "survey_completed",
                "was_session_held",
            ],
        }
    )
    return {
        "dim_employer": dim_employer,
        "dim_survey_response": responses,
        "fact_survey_answer": answers,
        "question_catalogue": catalogue,
        "fact_engagement": engagement,
        "badges": pd.DataFrame({"employer_id": ["E1"], "badge": ["Active employer"]}),
        "fact_event": pd.DataFrame(
            {
                "event_name": ["Webinar 1", "Webinar 1", "Workshop 4"],
                "action": ["signup", "attended", "signup"],
            }
        ),
    }


ALL: dd.Filters = {"sector": ["Public", "Private", "Unknown"]}


# ---------------------------------------------------------------- page 1


def test_survey_percent_is_ticks_over_people_who_answered() -> None:
    """Percent = ticks / respondents to this question; unchosen options show 0."""
    options, respondents = dd.survey_question_results(
        tables_for_tests(), "Q04", date(2026, 1, 1), date(2026, 12, 31), ALL
    )
    options = options.set_index("answer")
    assert respondents == 3  # R4 answered a different question only
    assert options.loc["A", "ticks"] == 2
    assert options.loc["A", "percent"] == pytest.approx(200 / 3)
    assert options.loc["B", "percent"] == pytest.approx(200 / 3)
    assert options.loc["C", "ticks"] == 0  # options nobody chose are still listed
    assert (options["percent"] == options["ticks"] / options["respondents"] * 100).all()


def test_survey_filters_and_dates_change_the_base() -> None:
    """Filters and the date range change who counts as a respondent."""
    tables = tables_for_tests()
    options, respondents = dd.survey_question_results(
        tables, "Q04", date(2026, 1, 1), date(2026, 12, 31), {"sector": ["Public"]}
    )
    assert respondents == 2  # R1 and R3
    assert options.set_index("answer").loc["A", "percent"] == pytest.approx(50.0)
    _, respondents = dd.survey_question_results(
        tables, "Q04", date(2026, 2, 1), date(2026, 2, 28), ALL
    )
    assert respondents == 1  # only R2 is in February


# ---------------------------------------------------------------- page 2


def test_employer_summary_counts_and_dates() -> None:
    """Counts per event type; future events are left out of the last engagement date."""
    s = dd.employer_summary(tables_for_tests(), ["E1"], today=date(2026, 10, 10))
    assert s["users"] == 2
    assert s["was_relationships"] == 1
    assert s["first_date"] == T("2025-11-01") and s["first_precision"] == "month"
    assert s["last_date"] == T("2026-02-15")  # the 2030 session is in the future
    assert s["future_events"] == 1
    assert s["badges"] == ["Active employer"]


def test_format_long_date() -> None:
    """Ordinal suffixes, month-only dates and missing dates."""
    assert dd.format_long_date(T("2025-12-04")) == "4th December 2025"
    assert dd.format_long_date(T("2026-07-01")) == "1st July 2026"
    assert dd.format_long_date(T("2026-07-12")) == "12th July 2026"
    assert dd.format_long_date(T("2025-11-01"), "month") == "November 2025"
    assert dd.format_long_date(None) == "Not recorded"


def test_natural_sort() -> None:
    """Numbers inside names sort as numbers."""
    assert sorted(["Org 10", "Org 2", "Org 1"], key=dd.natural_key) == ["Org 1", "Org 2", "Org 10"]


# ---------------------------------------------------------------- page 3


def test_monthly_counts_fill_empty_months_and_add_up() -> None:
    """Months with no events appear as 0 and the running total adds up."""
    result, undated = dd.monthly_counts(
        tables_for_tests(), "account_signup", date(2025, 11, 1), date(2026, 1, 31), ALL
    )
    assert list(result["month"]) == [T("2025-11-01"), T("2025-12-01"), T("2026-01-01")]
    assert list(result["count"]) == [1, 0, 2]
    assert list(result["cumulative"]) == [1, 1, 3]
    assert undated == 0


def test_monthly_counts_keep_events_with_no_employer_as_unknown() -> None:
    """An event with no employer counts as Unknown sector, not as missing."""
    tables = tables_for_tests()
    result, _ = dd.monthly_counts(
        tables, "survey_completed", date(2026, 1, 1), date(2026, 1, 31), ALL
    )
    assert result["count"].sum() == 1
    result, _ = dd.monthly_counts(
        tables, "survey_completed", date(2026, 1, 1), date(2026, 1, 31), {"sector": ["Public"]}
    )
    assert result["count"].sum() == 0


# ---------------------------------------------------------------- page 4


def test_event_counts() -> None:
    """Counts follow the chosen order and events with no rows get 0."""
    counts = dd.event_counts(tables_for_tests(), ["Webinar 1", "Workshop 4", "Webinar 3"], "signup")
    assert list(counts["count"]) == [1, 1, 0]


# ---------------------------------------------------------------- the app itself


@pytest.fixture(scope="module")
def built_output(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Run wrangle.py into a temp folder, plus three made-up event rows for page 4."""
    folder = tmp_path_factory.mktemp("output")
    wrangle.run(ROOT / "config.toml", output_folder=folder)
    events = pd.DataFrame(
        {
            "event_id": ["EV1", "EV1", "EV2"],
            "event_name": ["Webinar 1", "Webinar 1", "Workshop 4"],
            "event_type": ["webinar", "webinar", "workshop"],
            "event_date": ["2026-03-01"] * 3,
            "employer_id": ["", "", ""],
            "action": ["signup", "attended", "signup"],
            "action_date": ["2026-03-01"] * 3,
        }
    )
    events.to_csv(folder / "fact_event.csv", index=False)
    return folder


@pytest.mark.parametrize(
    "page", ["Home", "Employer view", "Engagement", "Events", "Survey findings"]
)
def test_every_page_renders(built_output: Path, monkeypatch: pytest.MonkeyPatch, page: str) -> None:
    """Each page runs without an exception on the real pipeline output."""
    from streamlit.testing.v1 import AppTest

    monkeypatch.setattr(dd, "OUTPUT", built_output)
    at = AppTest.from_file(str(ROOT / "dashboard.py"), default_timeout=60).run()
    at.sidebar.radio[0].set_value(page).run()
    if page == "Employer view":
        at.multiselect[0].set_value(["Org 1", "Org 29"]).run()
    assert not at.exception, at.exception
