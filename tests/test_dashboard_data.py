"""Checks on the dashboard's numbers, grouped by the function under test.

Most use a tiny made-up set of tables, so every expected number can be
worked out by hand.
"""

import os
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from hww_dashboard import dashboard_data as dd

T = pd.Timestamp
ALL: dd.Filters = {"sector": ["Public", "Private", "Unknown"]}


@pytest.fixture
def tables() -> dd.Tables:
    """A tiny made-up set of tables.

    Two employers, E1 (Public) and E2 (Private). Survey: R1 and R3 are
    E1's, R2 is E2's and R4 has no employer. For Q04, R1 ticks A and B,
    R2 ticks A and R3 ticks B; R4 answers only Q01. Engagement: E1 has
    two sign-ups, a WAS request and a session booked for 2030; E2 has
    one sign-up; one survey has no employer.

    Returns:
        Table name -> table, shaped like ``dd.load_tables`` output.
    """
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
            "date": [
                T("2026-01-10"),
                T("2026-02-10"),
                T("2026-03-10"),
                T("2026-03-11"),
            ],
            "sector": ["Public", "Private", "Public", "Unknown"],
            "industry": ["Education", "Retail", "Education", "Unknown"],
            "size_band": ["1000+", "0-9", "1000+", "Unknown"],
            "sites_band": ["6+", "1", "6+", "Unknown"],
        }
    )
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
        "badges": pd.DataFrame(
            {"employer_id": ["E1"], "badge": ["Active employer"]}
        ),
        "fact_event": pd.DataFrame(
            {
                "event_name": ["Webinar 1", "Webinar 1", "Workshop 4"],
                "action": ["signup", "attended", "signup"],
            }
        ),
    }


class TestLoadTables:
    """``load_tables``: read the CSVs that wrangle wrote."""

    def test_reads_dates_and_answer_order(self, pipeline_output: Path) -> None:
        """Date columns become Timestamps and answer_order whole numbers."""
        tables = dd.load_tables(pipeline_output)
        assert set(tables) == set(dd.DATE_COLUMNS)
        dates = tables["fact_engagement"]["date"]
        assert pd.api.types.is_datetime64_any_dtype(dates)
        order = tables["question_catalogue"]["answer_order"]
        assert pd.api.types.is_integer_dtype(order)

    def test_missing_table_says_to_run_wrangle(self, tmp_path: Path) -> None:
        """An empty folder is reported with the command that fills it."""
        with pytest.raises(
            FileNotFoundError, match=r"Run 'python wrangle.py' first"
        ):
            dd.load_tables(tmp_path)


class TestDataStamp:
    """``data_stamp``: the cache key that changes when wrangle runs."""

    def test_is_the_latest_csv_change_time(self, tmp_path: Path) -> None:
        """The newest CSV's time counts; other files are ignored."""
        for name, saved in (("a.csv", 100), ("b.csv", 300), ("c.md", 900)):
            path = tmp_path / name
            path.write_text("x", encoding="utf-8")
            os.utime(path, (saved, saved))
        assert dd.data_stamp(tmp_path) == 300

    def test_is_zero_with_no_csvs(self, tmp_path: Path) -> None:
        """A folder wrangle has not written to gives 0."""
        assert dd.data_stamp(tmp_path) == 0


class TestSurveyQuestionResults:
    """``survey_question_results``: the Figure 13 numbers (page 1)."""

    def test_percent_is_ticks_over_people_who_answered(
        self, tables: dd.Tables
    ) -> None:
        """Percent = ticks / respondents to this question; unchosen show 0."""
        options, respondents = dd.survey_question_results(
            tables, "Q04", date(2026, 1, 1), date(2026, 12, 31), ALL
        )
        options = options.set_index("answer")
        assert respondents == 3  # R4 answered a different question only
        assert options.loc["A", "ticks"] == 2
        assert options.loc["A", "percent"] == pytest.approx(200 / 3)
        assert options.loc["B", "percent"] == pytest.approx(200 / 3)
        assert options.loc["C", "ticks"] == 0  # unchosen options are listed
        expected = options["ticks"] / options["respondents"] * 100
        assert (options["percent"] == expected).all()

    def test_filters_and_dates_change_the_base(
        self, tables: dd.Tables
    ) -> None:
        """Filters and the date range change who counts as a respondent."""
        options, respondents = dd.survey_question_results(
            tables,
            "Q04",
            date(2026, 1, 1),
            date(2026, 12, 31),
            {"sector": ["Public"]},
        )
        assert respondents == 2  # R1 and R3
        percent = options.set_index("answer").loc["A", "percent"]
        assert percent == pytest.approx(50.0)
        _, respondents = dd.survey_question_results(
            tables, "Q04", date(2026, 2, 1), date(2026, 2, 28), ALL
        )
        assert respondents == 1  # only R2 is in February


class TestEmployerSummary:
    """``employer_summary``: the headline numbers (page 2)."""

    def test_counts_and_dates(self, tables: dd.Tables) -> None:
        """Counts per event type; future events are not 'most recent'."""
        s = dd.employer_summary(tables, ["E1"], today=date(2026, 10, 10))
        assert s["users"] == 2
        assert s["was_relationships"] == 1
        assert s["first_date"] == T("2025-11-01")
        assert s["first_precision"] == "month"
        assert s["last_date"] == T("2026-02-15")  # 2030 is in the future
        assert s["future_events"] == 1
        assert s["badges"] == ["Active employer"]


class TestFormatLongDate:
    """``format_long_date``: dates written as the mockups write them."""

    def test_day_dates_get_ordinal_suffixes(self) -> None:
        """1st, 4th and 12th, with the month and year in full."""
        assert dd.format_long_date(T("2025-12-04")) == "4th December 2025"
        assert dd.format_long_date(T("2026-07-01")) == "1st July 2026"
        assert dd.format_long_date(T("2026-07-12")) == "12th July 2026"

    def test_month_precision_shows_the_month(self) -> None:
        """Sign-ups are only known to the month."""
        assert dd.format_long_date(T("2025-11-01"), "month") == "November 2025"

    def test_missing_date_is_not_recorded(self) -> None:
        """No date gives 'Not recorded'."""
        assert dd.format_long_date(None) == "Not recorded"


class TestNaturalKey:
    """``natural_key``: sort names the way people read them."""

    def test_numbers_sort_as_numbers(self) -> None:
        """Org 2 comes before Org 10."""
        names = sorted(["Org 10", "Org 2", "Org 1"], key=dd.natural_key)
        assert names == ["Org 1", "Org 2", "Org 10"]


class TestMonthlyCounts:
    """``monthly_counts``: events per month and running total (page 3)."""

    def test_empty_months_are_zero_and_the_total_adds_up(
        self, tables: dd.Tables
    ) -> None:
        """Months with no events appear as 0; the running total adds up."""
        result, undated = dd.monthly_counts(
            tables, "account_signup", date(2025, 11, 1), date(2026, 1, 31), ALL
        )
        assert list(result["month"]) == [
            T("2025-11-01"),
            T("2025-12-01"),
            T("2026-01-01"),
        ]
        assert list(result["count"]) == [1, 0, 2]
        assert list(result["cumulative"]) == [1, 1, 3]
        assert undated == 0

    def test_events_with_no_employer_count_as_unknown(
        self, tables: dd.Tables
    ) -> None:
        """An event with no employer has Unknown sector, not none."""
        start, end = date(2026, 1, 1), date(2026, 1, 31)
        result, _ = dd.monthly_counts(
            tables, "survey_completed", start, end, ALL
        )
        assert result["count"].sum() == 1
        result, _ = dd.monthly_counts(
            tables, "survey_completed", start, end, {"sector": ["Public"]}
        )
        assert result["count"].sum() == 0


class TestEventCounts:
    """``event_counts``: rows per chosen event for one action (page 4)."""

    def test_follow_the_chosen_order_with_zeros(
        self, tables: dd.Tables
    ) -> None:
        """Counts follow the chosen order; events with no rows get 0."""
        counts = dd.event_counts(
            tables, ["Webinar 1", "Workshop 4", "Webinar 3"], "signup"
        )
        assert list(counts["count"]) == [1, 1, 0]
