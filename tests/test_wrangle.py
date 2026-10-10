"""Checks on the wrangling pipeline. Run with: python -m pytest."""

import re
import sys
import tomllib
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import wrangle

CONFIG = ROOT / "config.toml"


@pytest.fixture(scope="module")
def output(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Run the whole pipeline once into a temporary folder and return that folder."""
    folder = tmp_path_factory.mktemp("output")
    wrangle.run(CONFIG, output_folder=folder)
    return folder


def read_outputs(folder: Path) -> dict[str, pd.DataFrame]:
    """Read every output CSV as text, keyed by table name."""
    return {p.stem: pd.read_csv(p, dtype=str, keep_default_na=False) for p in folder.glob("*.csv")}


# ---------------------------------------------------------------- privacy


def test_no_personal_columns_in_output(output: Path) -> None:
    """No column named in [privacy] personal_columns reaches any output table."""
    with open(CONFIG, "rb") as f:
        personal = {c.casefold() for c in tomllib.load(f)["privacy"]["personal_columns"]}
    for name, df in read_outputs(output).items():
        found = [c for c in df.columns if c.casefold() in personal]
        assert not found, f"{name}.csv has personal column(s) {found}"


def test_no_personal_values_in_output(output: Path) -> None:
    """No email addresses, IP addresses or web links anywhere in the output cells."""
    email = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
    ip = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
    link = re.compile(r"https?://")
    for name, df in read_outputs(output).items():
        for column in df.columns:
            for value in df[column]:
                assert not email.search(value), f"{name}.{column} contains an email: {value}"
                assert not ip.search(value), f"{name}.{column} contains an IP address: {value}"
                assert not link.search(value), f"{name}.{column} contains a link: {value}"


# ---------------------------------------------------------------- keys


def test_every_employer_id_exists_in_dim_employer(output: Path) -> None:
    """employer_id is unique in dim_employer and every other table only uses known ids."""
    tables = read_outputs(output)
    ids = set(tables["dim_employer"]["employer_id"])
    assert len(ids) == len(tables["dim_employer"]), "employer_id is not unique in dim_employer"
    for name, df in tables.items():
        if name == "dim_employer" or "employer_id" not in df.columns:
            continue
        unknown = set(df["employer_id"]) - ids - {""}
        assert not unknown, (
            f"{name}.csv has employer_id(s) missing from dim_employer: {sorted(unknown)[:5]}"
        )


def test_dim_employer_has_one_row_per_name(output: Path) -> None:
    """Names that differ only by case are merged into one employer."""
    names = read_outputs(output)["dim_employer"]["employer_name"].str.casefold()
    assert not names.duplicated().any()


def test_every_signup_row_is_kept(output: Path) -> None:
    """Duplicate organisations are merged in dim_employer, but every sign-up row stays a user."""
    with open(CONFIG, "rb") as f:
        cfg = tomllib.load(f)
    s = cfg["signups"]
    raw = wrangle.read_sheet(
        ROOT / cfg["paths"]["input_folder"] / s["file"], s["sheet"], s["header_row"]
    )
    expected = (raw[s["org"]].map(wrangle.clean_text) != "").sum()
    tables = read_outputs(output)
    assert len(tables["fact_signup"]) == expected
    assert (tables["fact_engagement"]["event_type"] == "account_signup").sum() == expected


def test_every_survey_answer_is_in_the_catalogue(output: Path) -> None:
    """Every answer row links to a question_catalogue row."""
    answers = read_outputs(output)["fact_survey_answer"]
    assert (answers["answer_id"] != "").all()


# ---------------------------------------------------------------- survey percentages


def test_figure_13_percentages_are_ticks_over_respondents() -> None:
    """Three responses to a made-up wide export.

    Percent = ticks / people who answered the question.
    """
    wide = pd.DataFrame(
        {
            "response_id": ["R1", "R2", "R3"],
            "Minor illness": ["Minor illness", "Minor illness", ""],
            "Mental health": ["Mental health", "", ""],
            "Other": ["Other", "", ""],
            "Other.1": ["my free text", "", ""],
            "Flexible?": ["Yes", "Weithiau", "No"],
        }
    )
    columns_map = pd.DataFrame(
        [
            ["Minor illness", "tick", "Q04", "Minor illness"],
            ["Mental health", "tick", "Q04", "Mental health"],
            ["Other", "tick", "Q04", "Other"],
            ["Other.1", "other_text", "Q04", ""],
            ["Flexible?", "single", "Q14", ""],
        ],
        columns=["column", "role", "question_id", "option_or_note"],
    )
    answer_lookup = {("Q14", "yes"): "Yes", ("Q14", "sometimes"): "Sometimes", ("Q14", "no"): "No"}
    translations = {("Q14", "weithiau"): "Sometimes"}

    answers, other_text, _ = wrangle.unpivot_survey(
        wide, columns_map, answer_lookup, translations, False
    )

    q4 = wrangle.survey_percentages(answers, "Q04").set_index("answer")
    # R3 ticked nothing, so only R1 and R2 count as respondents.
    assert (q4["respondents"] == 2).all()
    assert q4.loc["Minor illness", "ticks"] == 2
    assert q4.loc["Minor illness", "percent"] == pytest.approx(100.0)
    assert q4.loc["Mental health", "percent"] == pytest.approx(50.0)
    assert q4.loc["Other", "percent"] == pytest.approx(50.0)
    assert (q4["percent"] == q4["ticks"] / q4["respondents"] * 100).all()

    # Free text stays out, and the Welsh answer is translated.
    assert "my free text" not in set(answers["answer"])
    assert other_text.empty
    q14 = wrangle.survey_percentages(answers, "Q14").set_index("answer")
    assert q14.loc["Sometimes", "ticks"] == 1
    assert q14["respondents"].iloc[0] == 3


def test_output_has_at_most_one_tick_per_respondent_and_option(output: Path) -> None:
    """So counting rows in fact_survey_answer gives the tick count."""
    answers = read_outputs(output)["fact_survey_answer"]
    assert not answers.duplicated(["response_id", "question_id", "answer"]).any()


# ---------------------------------------------------------------- free-text flags


@pytest.mark.parametrize(
    "text, signup_month, flag, dates",
    [
        ("", date(2025, 11, 1), False, []),
        ("Y", date(2025, 11, 1), True, []),
        ("\nY (Dec)", date(2025, 11, 1), True, [date(2025, 12, 1)]),
        ("Y (Dec)", date(2026, 1, 1), True, [date(2025, 12, 1)]),
        ("Y (Jan)", date(2025, 12, 1), True, [date(2026, 1, 1)]),
        ("Y (Nov 25 & Aug 26)", date(2025, 11, 1), True, [date(2025, 11, 1), date(2026, 8, 1)]),
        ("Y (March 2026)", date(2026, 2, 1), True, [date(2026, 3, 1)]),
        ("Y (Sept 26)", date(2026, 7, 1), True, [date(2026, 9, 1)]),
        ("maybe", date(2026, 7, 1), None, []),
    ],
)
def test_parse_flag(text: str, signup_month: date, flag: bool | None, dates: list[date]) -> None:
    """'Y (Dec)' style text gives a flag and first-of-month dates, guessing missing years."""
    got_flag, got_dates, _ = wrangle.parse_flag(text, signup_month)
    assert got_flag == flag
    assert got_dates == dates


def test_clean_text_handles_mixed_types_and_stray_newlines() -> None:
    """Numbers, blanks, newlines and Excel's _x000D_ all come out as tidy text."""
    assert wrangle.clean_text(1) == wrangle.clean_text("1") == wrangle.clean_text(1.0) == "1"
    assert wrangle.clean_text("\n2-5") == "2-5"
    assert wrangle.clean_text("Sleep_x000D_\nGambling") == "Sleep Gambling"
    assert wrangle.clean_text(None) == wrangle.clean_text(float("nan")) == ""
