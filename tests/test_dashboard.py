"""Smoke tests: every dashboard page draws from the pipeline's output.

Each page runs in Streamlit's AppTest on the output of one run on the
synthetic inputs, with today fixed at 10 October 2026, so what the pages
show does not depend on the real date. Grouped by page.
"""

import shutil
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

PageOpener = Callable[[str], AppTest]


def run_dashboard(root: str, today: str) -> None:
    """Draw the dashboard as the launcher does, with a fixed today.

    AppTest runs a copy of this function's source as the app's script,
    so the function imports what it needs itself.

    Args:
        root: Project folder whose output/ holds the tables.
        today: The date to treat as today, as YYYY-MM-DD.
    """
    import datetime
    import pathlib

    from hww_dashboard.dashboard import main

    main(pathlib.Path(root), datetime.date.fromisoformat(today))


def text_of(at: AppTest) -> str:
    """Join the text of every markdown element the app drew.

    Args:
        at: An app that has run.

    Returns:
        The elements' markdown and HTML, one per line.
    """
    return "\n".join(element.value for element in at.markdown)


@pytest.fixture(scope="module")
def app_root(
    tmp_path_factory: pytest.TempPathFactory, pipeline_output: Path
) -> Path:
    """A project folder whose output/ is the pipeline's, plus events.

    fact_event.csv has no source yet, so three made-up event rows are
    added for the Events page to chart.

    Returns:
        The folder to pass to the app as its project folder.
    """
    root = tmp_path_factory.mktemp("app")
    shutil.copytree(pipeline_output, root / "output")
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
    events.to_csv(root / "output" / "fact_event.csv", index=False)
    return root


@pytest.fixture
def open_page(app_root: Path, today: date) -> PageOpener:
    """Open the dashboard on a page.

    Returns:
        A function that takes a page name and returns the app after that
        page has run.
    """

    def open_(page: str) -> AppTest:
        """Run the app and choose a page in the sidebar menu.

        Args:
            page: A page name, as in the menu.

        Returns:
            The app, after the page has run.
        """
        at = AppTest.from_function(
            run_dashboard,
            kwargs={"root": str(app_root), "today": today.isoformat()},
            default_timeout=60,
        )
        at.run()
        at.sidebar.radio[0].set_value(page).run()
        return at

    return open_


class TestHomePage:
    """The Home page: headline numbers and the data quality report."""

    def test_shows_the_headline_numbers(self, open_page: PageOpener) -> None:
        """The four numbers count employers and engagement events."""
        at = open_page("Home")
        assert not at.exception, at.exception
        metrics = {metric.label: metric.value for metric in at.metric}
        assert metrics == {
            "Employers": "168",
            "Website account sign ups": "185",
            "Employer survey responses": "103",
            "WAS requests": "35",
        }


class TestEmployerViewPage:
    """The Employer view page (mockup page 2)."""

    def test_draws_for_several_employers(self, open_page: PageOpener) -> None:
        """Choosing two employers draws without an error."""
        at = open_page("Employer view")
        at.multiselect[0].set_value(["Org 1", "Org 29"]).run()
        assert not at.exception, at.exception

    def test_org_11_engagement(self, open_page: PageOpener) -> None:
        """Org 11's numbers match the pipeline guide's worked example."""
        at = open_page("Employer view")
        at.multiselect[0].set_value(["Org 11"]).run()
        assert not at.exception, at.exception
        text = text_of(at)
        assert '<span class="num">2</span><span>Users</span>' in text
        assert "<span>November 2025</span>" in text
        assert "<span>21st September 2026</span>" in text

    def test_future_session_is_not_engagement_yet(
        self, open_page: PageOpener
    ) -> None:
        """Org 31's session on 11 October 2026 is after today."""
        at = open_page("Employer view")
        at.multiselect[0].set_value(["Org 31"]).run()
        assert not at.exception, at.exception
        captions = [caption.value for caption in at.caption]
        assert (
            "1 event(s) dated in the future (e.g. booked WAS sessions) are "
            "not counted as engagement yet." in captions
        )


class TestEngagementPage:
    """The Engagement page (mockup page 3)."""

    def test_draws_the_monthly_chart(self, open_page: PageOpener) -> None:
        """The default metric draws its chart and the sign-up note."""
        at = open_page("Engagement")
        assert not at.exception, at.exception
        assert at.get("plotly_chart")
        notes = [caption.value for caption in at.caption]
        assert any("recorded by month" in note for note in notes)


class TestEventsPage:
    """The Events page (mockup page 4)."""

    def test_draws_the_event_chart(self, open_page: PageOpener) -> None:
        """With event rows to show, the page charts them."""
        at = open_page("Events")
        assert not at.exception, at.exception
        assert at.get("plotly_chart")


class TestSurveyFindingsPage:
    """The Survey findings page (mockup page 1)."""

    def test_draws_the_answer_chart(self, open_page: PageOpener) -> None:
        """The default question draws from every response, with no warning."""
        at = open_page("Survey findings")
        assert not at.exception, at.exception
        assert at.get("plotly_chart")
        assert not any("respondent(s)" in w.value for w in at.warning)

    def test_warns_on_few_respondents(self, open_page: PageOpener) -> None:
        """The 8 responses up to 17 November 2025 get the warning."""
        at = open_page("Survey findings")
        at.date_input(key="survey_end").set_value(date(2025, 11, 17)).run()
        assert not at.exception, at.exception
        assert at.get("plotly_chart")
        assert any("Only 8 respondent(s)" in w.value for w in at.warning)


class TestLauncher:
    """``streamlit run dashboard.py``: the launcher in the project folder."""

    def test_reads_the_folder_named_by_hww_output(
        self,
        project_folder: Path,
        app_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """HWW_OUTPUT points the app at another output folder.

        Only the test folder has event rows, so a chart on the Events
        page shows it was read.
        """
        monkeypatch.setenv("HWW_OUTPUT", str(app_root / "output"))
        launcher = project_folder / "dashboard.py"
        at = AppTest.from_file(str(launcher), default_timeout=60).run()
        assert not at.exception, at.exception
        assert at.title[0].value == "HWW dashboard"
        at.sidebar.radio[0].set_value("Events").run()
        assert not at.exception, at.exception
        assert at.get("plotly_chart")
