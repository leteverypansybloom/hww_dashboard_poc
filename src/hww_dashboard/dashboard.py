"""Healthy Working Wales monitoring dashboard: the Streamlit app.

Run wrangle first, then start the app from the project folder with
``streamlit run dashboard.py``. That launcher calls :func:`main` on
every rerun.

Pages follow the mockups: Home, Employer view, Engagement, Events,
Survey findings. The numbers come from
:mod:`hww_dashboard.dashboard_data`; this module only draws them.
"""

import html
import os
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from hww_dashboard import dashboard_data as dd

# Colours. One colour per chart (every chart here shows a single series).
NAVY = "#232a6b"  # HWW navy, bars (13:1 contrast on white)
# A darker step of HWW teal, for lines (4.2:1 on white; the bright brand
# teal is too pale).
TEAL = "#178a7d"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
FONT = "system-ui, -apple-system, 'Segoe UI', sans-serif"

# Warn when a chart rests on fewer than this many respondents or events.
SMALL_N = 10

PAGES = ["Home", "Employer view", "Engagement", "Events", "Survey findings"]
# Page titles that differ from the page's name in the menu.
TITLES = {"Home": "HWW dashboard"}

# Optional: save the HWW logo here, under the project folder, and it
# replaces the text name at the top right of every page.
LOGO = Path("assets") / "logo.png"

STYLE = """
<style>
  .hww-brand { text-align: right; line-height: 1.15; }
  .hww-brand .cy { color: #178a7d; font-size: 1.15rem; font-weight: 600; }
  .hww-brand .en { color: #232a6b; font-size: 1.15rem; font-weight: 600; }
  .hww-block {
    border-top: 1px solid #52514e;
    padding: 0.6rem 0;
    margin-bottom: 0.4rem;
  }
  .hww-block:last-of-type { border-bottom: 1px solid #52514e; }
  .hww-row {
    display: flex;
    gap: 1.5rem;
    font-size: 1.1rem;
    padding: 0.15rem 0;
  }
  .hww-row .num { min-width: 3.5rem; font-weight: 600; }
  .hww-row .lbl { min-width: 16rem; }
</style>
"""


# ---------------------------------------------------------------- shared


@st.cache_data
def load(folder: Path, stamp: float) -> dd.Tables:
    """Read the CSVs once per change of the output folder.

    Args:
        folder: Folder of CSVs written by wrangle.
        stamp: From ``dd.data_stamp()``. It changes when wrangle rewrites
            the CSVs, which makes Streamlit's cache run this again.

    Returns:
        The tables from ``dd.load_tables()``.
    """
    return dd.load_tables(folder)


def header(title: str, logo: Path) -> None:
    """Draw the page title, with the HWW logo or name on the right.

    Args:
        title: Page title.
        logo: The logo image. The bilingual name is shown instead when
            the file does not exist.
    """
    left, right = st.columns([3, 1])
    left.title(title)
    if logo.exists():
        right.image(str(logo))
    else:
        right.markdown(
            '<div class="hww-brand">'
            '<div class="cy">Cymru Iach ar Waith</div>'
            '<div class="en">Healthy Working Wales</div></div>',
            unsafe_allow_html=True,
        )


def style(fig: go.Figure, height: int) -> go.Figure:
    """Apply quiet chart chrome: white surface, hairline grid, no legend.

    Every chart here shows a single series, so none needs a legend.

    Args:
        fig: The chart (changed in place).
        height: Chart height in pixels.

    Returns:
        The same chart, so calls can be chained.
    """
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=48, t=96, b=8),
        paper_bgcolor="white",
        plot_bgcolor="white",
        font=dict(family=FONT, size=13, color=INK_2),
        title=dict(
            x=0,
            xanchor="left",
            y=1,
            yref="container",
            yanchor="top",
            pad=dict(t=8),
            font=dict(size=16, color=INK),
        ),
        showlegend=False,
        hoverlabel=dict(
            bgcolor="white",
            bordercolor=GRID,
            font=dict(family=FONT, color=INK),
        ),
    )
    fig.update_xaxes(
        gridcolor=GRID,
        linecolor=AXIS,
        zeroline=False,
        tickfont=dict(color=MUTED),
        automargin=True,
    )
    fig.update_yaxes(
        gridcolor=GRID,
        linecolor=AXIS,
        zeroline=False,
        tickfont=dict(color=MUTED),
        automargin=True,
    )
    return fig


def whole_number_ticks(largest: float) -> dict[str, Any]:
    """Make axis settings for counts: no 0.5 ticks, step 1 for small counts.

    Args:
        largest: The biggest value on the axis.

    Returns:
        Keyword arguments for ``fig.update_yaxes`` / ``update_xaxes``.
    """
    return dict(
        tickformat=",d", dtick=1 if largest <= 5 else None, rangemode="tozero"
    )


def show_chart(fig: go.Figure) -> None:
    """Draw a chart with the HWW styling (not Streamlit's) and no logo.

    Args:
        fig: The chart.
    """
    st.plotly_chart(fig, theme=None, config={"displaylogo": False})


def date_range(dates: pd.Series, key: str, today: date) -> tuple[date, date]:
    """Draw start and end date pickers, defaulting to the data's range.

    The default end is never after today.

    Args:
        dates: The dates in the data (NaT is ignored).
        key: Prefix for the widget keys, unique per page.
        today: Today's date.

    Returns:
        (start, end). Start may be after end: an error is shown and
        callers should stop.
    """
    valid = dates.dropna()
    first = valid.min().date() if len(valid) else today
    last = min(valid.max().date(), today) if len(valid) else today
    start = st.date_input(
        "Start date", first, format="DD/MM/YYYY", key=f"{key}_start"
    )
    end = st.date_input(
        "End date", last, format="DD/MM/YYYY", key=f"{key}_end"
    )
    if start > end:
        st.error("Start date is after end date.")
    return start, end


def choice_filter(label: str, options: Sequence[str], key: str) -> list[str]:
    """Draw a multi-choice filter with every option selected to start with.

    As in the mockups. Short lists are pills. Long lists are checkboxes
    in a collapsed box whose title says how many are on.

    Args:
        label: Filter label.
        options: Choices, in display order.
        key: Widget key, unique per page and filter.

    Returns:
        The chosen options.
    """
    if len(options) <= 6:
        chosen = st.pills(
            label,
            options,
            selection_mode="multi",
            default=options,
            key=key,
            wrap=True,
        )
        return list(chosen or [])
    on = [o for o in options if st.session_state.get(f"{key}_{o}", True)]
    # The key keeps the box open while its title (the count) changes.
    with st.expander(
        f"{label}: {len(on)} of {len(options)} selected", key=f"{key}_box"
    ):
        return [
            o for o in options if st.checkbox(o, value=True, key=f"{key}_{o}")
        ]


def employer_filters(
    tables: dd.Tables, key: str, include_size: bool = True
) -> dict[str, list[str]]:
    """Draw the sector / industry / (size) / sites filters.

    Args:
        tables: From ``load``.
        key: Page name; ``"survey"`` also offers values found only on
            survey responses.
        include_size: Show the number-of-employees filter.

    Returns:
        {column: chosen values}, ready for ``dd.apply_filters``.
    """
    sources = [tables["dim_employer"]]
    if key == "survey":
        sources.append(tables["dim_survey_response"])
    fields = [("sector", "Employer sector"), ("industry", "Employer industry")]
    if include_size:
        fields.append(("size_band", "Number of employees"))
    fields.append(("sites_band", "Number of sites in Wales"))
    filters = {}
    for column, label in fields:
        # Unknown is always offered: events or responses with no linked
        # employer count as Unknown.
        options = dd.ordered_options(
            column, [dd.UNKNOWN], *[s[column] for s in sources]
        )
        filters[column] = choice_filter(label, options, f"{key}_{column}")
    return filters


def small_numbers_warning(n: int, what: str) -> None:
    """Warn when a chart rests on fewer than ``SMALL_N`` people or records.

    Args:
        n: How many the chart is based on.
        what: Singular noun for the message, e.g. ``"respondent"``.
    """
    if 0 < n < SMALL_N:
        st.warning(
            f"Only {n} {what}(s) match these filters. "
            "Patterns based on small numbers are not robust and should not "
            "be published."
        )


# ---------------------------------------------------------------- pages


def page_home(tables: dd.Tables, report: Path) -> None:
    """Draw the home page: headline numbers and the latest report.

    Args:
        tables: From ``load``.
        report: The data_quality_report.md written with the tables.
    """
    events = tables["fact_engagement"]["event_type"].value_counts()
    cols = st.columns(4)
    cols[0].metric("Employers", f"{len(tables['dim_employer']):,}")
    cols[1].metric(
        "Website account sign ups", f"{events.get('account_signup', 0):,}"
    )
    cols[2].metric(
        "Employer survey responses", f"{events.get('survey_completed', 0):,}"
    )
    cols[3].metric("WAS requests", f"{events.get('was_request', 0):,}")
    st.markdown("""
        Use the menu on the left:

        - **Employer view**: users, survey responses, WAS and peer
          mentoring for chosen employers.
        - **Engagement**: monthly and cumulative counts for sign ups,
          survey completions and WAS.
        - **Events**: sign ups, attendance and survey completion for
          events (no data yet).
        - **Survey findings**: answers to any Employer Survey Tool
          question, with filters.
        """)
    if report.exists():
        with st.expander("Data quality report from the last wrangle.py run"):
            st.markdown(report.read_text(encoding="utf-8"))


def page_employer(tables: dd.Tables, today: date) -> None:
    """Draw the employer view (mockup page 2).

    Counts, first and most recent engagement, and badges.

    Args:
        tables: From ``load``.
        today: Today's date. Later events are not counted as engagement.
    """
    dim = tables["dim_employer"]
    names = sorted(dim["employer_name"], key=dd.natural_key)
    chosen = st.multiselect(
        "Select employer(s)", names, placeholder="Choose one or more employers"
    )
    if not chosen:
        st.info("Choose one or more employers to see their engagement.")
        return

    ids = dim.loc[dim["employer_name"].isin(chosen), "employer_id"]
    s = dd.employer_summary(tables, ids, today)
    first = dd.format_long_date(s["first_date"], s["first_precision"])
    last = dd.format_long_date(s["last_date"], s["last_precision"])
    badges = ", ".join(s["badges"]) if s["badges"] else "None recorded"

    counts = [
        (s["users"], "Users"),
        (s["survey_responses"], "Responses to employer survey"),
        (s["was_relationships"], "Workplace Advisor Support relationships"),
        (s["peer_relationships"], "Peer mentoring relationships"),
    ]
    rows = "".join(
        f'<div class="hww-row"><span class="num">{n:,}</span>'
        f"<span>{label}</span></div>"
        for n, label in counts
    )
    dates = (
        '<div class="hww-row"><span class="lbl">First engagement on</span>'
        f"<span>{first}</span></div>"
        '<div class="hww-row"><span class="lbl">'
        "Most recent engagement on</span>"
        f"<span>{last}</span></div>"
    )
    badge_row = (
        '<div class="hww-row"><span>Badges</span>'
        f"<span>{html.escape(badges)}</span></div>"
    )
    st.markdown(
        f'<div class="hww-block">{rows}</div>'
        f'<div class="hww-block">{dates}</div>'
        f'<div class="hww-block">{badge_row}</div>',
        unsafe_allow_html=True,
    )
    notes = []
    if s["first_precision"] == "month":
        notes.append(
            "Account sign ups are only recorded by month, so the first "
            "engagement shows a month."
        )
    if s["future_events"]:
        notes.append(
            f"{s['future_events']} event(s) dated in the future (e.g. "
            "booked WAS sessions) are not counted as engagement yet."
        )
    for note in notes:
        st.caption(note)

    with st.expander("Employer details"):
        st.dataframe(
            dim[dim["employer_name"].isin(chosen)][
                [
                    "employer_name",
                    "sector",
                    "industry",
                    "size_band",
                    "sites_band",
                ]
            ],
            hide_index=True,
        )


def page_engagement(tables: dd.Tables, today: date) -> None:
    """Draw the engagement page (mockup page 3): monthly and cumulative.

    Args:
        tables: From ``load``.
        today: Today's date, the latest default end date.
    """
    left, right = st.columns([1, 2.6], gap="large")
    with left:
        label = st.radio("Select metric", list(dd.ENGAGEMENT_METRICS))
        event_type, title = dd.ENGAGEMENT_METRICS[label]
        start, end = date_range(
            tables["fact_engagement"]["date"], "engagement", today
        )
        filters = employer_filters(tables, "engagement", include_size=False)

    with right:
        if start > end:
            return
        result, undated = dd.monthly_counts(
            tables, event_type, start, end, filters
        )
        total = int(result["count"].sum())
        if total == 0:
            st.info("No events match these filters.")
            return
        small_numbers_warning(total, "event")
        show_chart(engagement_chart(result, title, start, end))

        notes = []
        if event_type == "account_signup":
            notes.append(
                "Sign ups are recorded by month. The date filter works on "
                "whole months."
            )
        if undated:
            notes.append(
                f"{undated} matching event(s) have no date and are not shown."
            )
        for note in notes:
            st.caption(note)
        with st.expander("Show data table"):
            table = result.assign(month=result["month"].dt.strftime("%b %Y"))
            st.dataframe(
                table.rename(columns={"count": "new"}), hide_index=True
            )


def engagement_chart(
    result: pd.DataFrame, title: str, start: date, end: date
) -> go.Figure:
    """Build monthly bars above a cumulative line, sharing the month axis.

    The mockup puts both on one chart with two y-axes. Two panels are
    used instead, because two y-scales on one plot invite a false
    comparison between them.

    Args:
        result: From ``dd.monthly_counts`` (month, count, cumulative).
        title: Chart title.
        start: Start of the date range, for the subtitle.
        end: End of the date range, for the subtitle.

    Returns:
        The styled chart.
    """
    months = result["month"].dt.strftime("%b %Y")
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.14,
        row_heights=[0.55, 0.45],
        subplot_titles=("New per month", "Cumulative"),
    )
    fig.add_trace(
        go.Bar(
            x=months,
            y=result["count"],
            marker=dict(color=NAVY, cornerradius=4),
            hovertemplate="%{x}<br><b>%{y:,}</b> new<extra></extra>",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=months,
            y=result["cumulative"],
            mode="lines+markers",
            line=dict(color=TEAL, width=2),
            marker=dict(size=8, color=TEAL, line=dict(color="white", width=2)),
            hovertemplate="%{x}<br><b>%{y:,}</b> in total<extra></extra>",
        ),
        row=2,
        col=1,
    )
    # Label only the end of the running total.
    fig.add_annotation(
        x=months.iloc[-1],
        y=result["cumulative"].iloc[-1],
        text=f"{result['cumulative'].iloc[-1]:,}",
        showarrow=False,
        xanchor="left",
        xshift=8,
        font=dict(color=INK, size=13),
        row=2,
        col=1,
    )
    # Keep columns thin: about 24px wide on a typical screen.
    fig.update_layout(bargap=max(0.3, 1 - 24 / (760 / max(len(result), 1))))
    fig.update_yaxes(**whole_number_ticks(result["count"].max()), row=1, col=1)
    fig.update_yaxes(
        **whole_number_ticks(result["cumulative"].max()), row=2, col=1
    )
    fig.update_annotations(
        selector=dict(text="New per month"),
        font=dict(size=13, color=INK_2),
        x=0,
        xanchor="left",
    )
    fig.update_annotations(
        selector=dict(text="Cumulative"),
        font=dict(size=13, color=INK_2),
        x=0,
        xanchor="left",
    )
    fig.update_layout(
        title=dict(
            text=f"{title}, monthly and cumulative",
            subtitle=dict(
                text=f"{start:%b %Y} to {end:%b %Y}",
                font=dict(color=INK_2, size=13),
            ),
        )
    )
    return style(fig, 560)


def page_events(tables: dd.Tables) -> None:
    """Draw the events page (mockup page 4): one metric for chosen events.

    Args:
        tables: From ``load``.
    """
    events = tables["fact_event"]
    names = sorted(set(events["event_name"]) - {""})
    left, right = st.columns([1, 2.6], gap="large")
    with left:
        chosen = (
            choice_filter("Select events", names, "events_names")
            if names
            else []
        )
        label = st.radio("Select metric", list(dd.EVENT_METRICS))
    with right:
        if not names:
            st.info(
                "No event data yet. When output/fact_event.csv has rows "
                "(one per sign up, attendance or completed survey), this "
                "page will chart them."
            )
            return
        if not chosen:
            st.info("Choose at least one event.")
            return
        counts = dd.event_counts(tables, chosen, dd.EVENT_METRICS[label])
        small_numbers_warning(int(counts["count"].sum()), "record")
        fig = go.Figure(
            go.Bar(
                x=counts["count"],
                y=counts["event_name"],
                orientation="h",
                marker=dict(color=NAVY, cornerradius=4),
                text=counts["count"],
                textposition="outside",
                cliponaxis=False,
                hovertemplate="%{y}<br><b>%{x:,}</b><extra></extra>",
            )
        )
        fig.update_layout(title=dict(text=f"{label} by event"), bargap=0.45)
        fig.update_yaxes(autorange="reversed", gridcolor="white")
        fig.update_xaxes(**whole_number_ticks(counts["count"].max()))
        show_chart(style(fig, 140 + 44 * len(counts)))
        with st.expander("Show data table"):
            st.dataframe(counts, hide_index=True)


def page_survey(tables: dd.Tables, today: date) -> None:
    """Draw the survey findings page (mockup page 1).

    Shows the % of respondents choosing each answer to a question.

    Args:
        tables: From ``load``.
        today: Today's date, the latest default end date.
    """
    catalogue = tables["question_catalogue"]
    questions = catalogue.drop_duplicates("question_id")
    labels = dict(
        zip(questions["question_id"], questions["question_short"], strict=True)
    )
    ids = list(labels)
    question_id = st.selectbox(
        "Select survey question",
        ids,
        format_func=lambda qid: labels[qid],
        index=ids.index("Q04") if "Q04" in ids else 0,
    )
    if question_id is None:
        st.info("question_catalogue.csv has no questions.")
        return

    left, right = st.columns([1, 2.6], gap="large")
    with left:
        start, end = date_range(
            tables["dim_survey_response"]["date"], "survey", today
        )
        filters = employer_filters(tables, "survey", include_size=True)

    with right:
        if start > end:
            return
        options, respondents = dd.survey_question_results(
            tables, question_id, start, end, filters
        )
        if respondents == 0:
            st.info("No survey responses match these filters.")
            return
        small_numbers_warning(respondents, "respondent")
        question = questions.loc[questions["question_id"] == question_id].iloc[
            0
        ]
        show_chart(survey_chart(options, question, respondents))
        if question["question_type"] == "multi":
            st.caption(
                "Respondents could choose more than one answer, "
                "so percentages can add up to more than 100%."
            )
        with st.expander("Show data table"):
            st.dataframe(
                options[["answer", "ticks", "respondents", "percent"]].round(
                    {"percent": 1}
                ),
                hide_index=True,
            )


def survey_chart(
    options: pd.DataFrame, question: pd.Series, respondents: int
) -> go.Figure:
    """Build horizontal bars of % of respondents per answer, like Figure 13.

    Multi-select questions are sorted by size; single-choice questions
    keep the form's order.

    Args:
        options: From ``dd.survey_question_results``.
        question: The question's row in question_catalogue.
        respondents: Number of respondents (the base for the percentages).

    Returns:
        The styled chart.
    """
    if question["question_type"] == "multi":
        ordered = options.sort_values(
            ["percent", "answer_order"], ascending=[True, False]
        )
    else:
        ordered = options.sort_values("answer_order", ascending=False)
    fig = go.Figure(
        go.Bar(
            x=ordered["percent"],
            y=ordered["answer_short"],
            orientation="h",
            marker=dict(color=NAVY, cornerradius=4),
            text=[f"{p:.0f}%" for p in ordered["percent"]],
            textposition="outside",
            cliponaxis=False,
            customdata=ordered[["ticks", "respondents", "answer"]].to_numpy(),
            hovertemplate=(
                "%{customdata[2]}<br><b>%{x:.1f}%</b> "
                "(%{customdata[0]} of %{customdata[1]})<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        title=dict(
            text=f"{question['question_short']} (n={respondents:,})",
            subtitle=dict(
                text=html.escape(question["question"], quote=False),
                font=dict(color=INK_2, size=12),
            ),
        ),
        bargap=0.4,
    )
    fig.update_xaxes(
        title=dict(text="Proportion of responses (%)", font=dict(color=INK_2)),
        range=[0, max(10, ordered["percent"].max() * 1.15)],
    )
    fig.update_yaxes(gridcolor="white")
    return style(fig, 130 + 34 * len(ordered))


# ---------------------------------------------------------------- main


def main(root: Path, today: date | None = None) -> None:
    """Draw the sidebar menu, the page header and the chosen page.

    Streamlit runs the launcher, and so this, on every interaction.

    Args:
        root: The project folder. The app reads the CSVs in its
            ``output`` folder, or in the folder named by the
            ``HWW_OUTPUT`` environment variable, and shows its
            ``assets/logo.png`` when that file exists.
        today: Treat this as today (the tests fix it). Defaults to the
            real date.
    """
    today = today or date.today()
    st.set_page_config(page_title="HWW dashboard", layout="wide")
    st.markdown(STYLE, unsafe_allow_html=True)
    output = Path(os.environ.get("HWW_OUTPUT", root / "output"))

    st.sidebar.title("HWW dashboard")
    page = st.sidebar.radio("Pages", PAGES, label_visibility="collapsed")
    try:
        tables = load(output, dd.data_stamp(output))
    except FileNotFoundError as error:
        st.error(str(error))
        st.stop()

    header(TITLES.get(page, page), root / LOGO)
    if page == "Home":
        page_home(tables, output / "data_quality_report.md")
    elif page == "Employer view":
        page_employer(tables, today)
    elif page == "Engagement":
        page_engagement(tables, today)
    elif page == "Events":
        page_events(tables)
    else:
        page_survey(tables, today)
