"""Checks on the wrangling pipeline, grouped by the function under test."""

import re
import tomllib
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import load_workbook

from hww_dashboard import wrangle

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
IP = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
LINK = re.compile(r"https?://")


def read_outputs(folder: Path) -> dict[str, pd.DataFrame]:
    """Read every output CSV in a folder as text.

    Args:
        folder: A pipeline output folder.

    Returns:
        Table name -> table, with blank cells as ''.
    """
    return {
        p.stem: pd.read_csv(p, dtype=str, keep_default_na=False)
        for p in folder.glob("*.csv")
    }


@pytest.fixture(scope="module")
def outputs(pipeline_output: Path) -> dict[str, pd.DataFrame]:
    """The tables written by one run on the synthetic inputs.

    Returns:
        Table name -> table, as text.
    """
    return read_outputs(pipeline_output)


@pytest.fixture(scope="module")
def settings(fixture_config: Path) -> wrangle.Config:
    """The frozen config that the run used.

    Returns:
        tests/data/config.toml as nested dicts.
    """
    with open(fixture_config, "rb") as f:
        return tomllib.load(f)


@pytest.fixture(scope="module")
def input_cells(data_folder: Path) -> list[str]:
    """Every non-blank cell of every synthetic input workbook, as text.

    Returns:
        The cells' values, headings included.
    """
    found: list[str] = []
    for path in sorted((data_folder / "inputs").glob("*.xlsx")):
        book = load_workbook(path, read_only=True, data_only=True)
        for sheet in book.worksheets:
            for row in sheet.iter_rows(values_only=True):
                found.extend(str(v) for v in row if v is not None)
        book.close()
    return found


@pytest.fixture
def unpivoted() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Three responses to a made-up wide export, unpivoted.

    Q04 is tick-box: R1 ticks Minor illness, Mental health and Other and
    types free text in the Other box, R2 ticks Minor illness and R3
    ticks nothing. Q14 is single-choice: the answers are Yes, Weithiau
    (Welsh for Sometimes) and No.

    Returns:
        (answers, other_text) from ``unpivot_survey``, without free text.
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
    answer_lookup = {
        ("Q14", "yes"): "Yes",
        ("Q14", "sometimes"): "Sometimes",
        ("Q14", "no"): "No",
    }
    translations = {("Q14", "weithiau"): "Sometimes"}
    answers, other_text, _ = wrangle.unpivot_survey(
        wide, columns_map, answer_lookup, translations, False
    )
    return answers, other_text


class TestRun:
    """``run``: privacy and key rules hold across the whole output."""

    def test_no_personal_columns_in_output(
        self, outputs: dict[str, pd.DataFrame], settings: wrangle.Config
    ) -> None:
        """No column named in [privacy] personal_columns reaches a table."""
        personal = {
            c.casefold() for c in settings["privacy"]["personal_columns"]
        }
        for name, df in outputs.items():
            found = [c for c in df.columns if c.casefold() in personal]
            assert not found, f"{name}.csv has personal column(s) {found}"

    def test_no_personal_values_in_output(
        self, outputs: dict[str, pd.DataFrame]
    ) -> None:
        """No email addresses, IP addresses or web links in any cell."""
        patterns = (
            (EMAIL, "an email"),
            (IP, "an IP address"),
            (LINK, "a link"),
        )
        for name, df in outputs.items():
            for column in df.columns:
                for value in df[column]:
                    for pattern, what in patterns:
                        assert not pattern.search(
                            value
                        ), f"{name}.{column} contains {what}: {value}"

    def test_every_employer_id_exists_in_dim_employer(
        self, outputs: dict[str, pd.DataFrame]
    ) -> None:
        """employer_id is unique in dim_employer; tables use known ids."""
        ids = set(outputs["dim_employer"]["employer_id"])
        rows = len(outputs["dim_employer"])
        assert len(ids) == rows, "employer_id is not unique in dim_employer"
        for name, df in outputs.items():
            if name == "dim_employer" or "employer_id" not in df.columns:
                continue
            unknown = set(df["employer_id"]) - ids - {""}
            assert not unknown, (
                f"{name}.csv has employer_id(s) missing from dim_employer: "
                f"{sorted(unknown)[:5]}"
            )

    def test_dim_employer_has_one_row_per_name(
        self, outputs: dict[str, pd.DataFrame]
    ) -> None:
        """Names that differ only by case are merged into one employer."""
        names = outputs["dim_employer"]["employer_name"].str.casefold()
        assert not names.duplicated().any()

    def test_every_signup_row_is_kept(
        self,
        outputs: dict[str, pd.DataFrame],
        settings: wrangle.Config,
        fixture_config: Path,
    ) -> None:
        """Every sign-up row stays a user, though employers are merged."""
        s = settings["signups"]
        inputs = fixture_config.parent / settings["paths"]["input_folder"]
        raw = wrangle.read_sheet(
            inputs / s["file"], s["sheet"], s["header_row"]
        )
        expected = (raw[s["org"]].map(wrangle.clean_text) != "").sum()
        events = outputs["fact_engagement"]["event_type"]
        assert len(outputs["fact_signup"]) == expected
        assert (events == "account_signup").sum() == expected

    def test_every_survey_answer_is_in_the_catalogue(
        self, outputs: dict[str, pd.DataFrame]
    ) -> None:
        """Every answer row links to a question_catalogue row."""
        answers = outputs["fact_survey_answer"]
        assert (answers["answer_id"] != "").all()

    def test_at_most_one_tick_per_respondent_and_option(
        self, outputs: dict[str, pd.DataFrame]
    ) -> None:
        """So counting rows in fact_survey_answer gives the tick count."""
        answers = outputs["fact_survey_answer"]
        key = ["response_id", "question_id", "answer"]
        assert not answers.duplicated(key).any()


class TestSyntheticInputs:
    """The committed inputs hold only reserved, synthetic personal data."""

    def test_personal_values_are_present(self, input_cells: list[str]) -> None:
        """Emails, IPs and links exist, so the privacy tests can fail."""
        assert any(EMAIL.search(cell) for cell in input_cells)
        assert any(IP.search(cell) for cell in input_cells)
        assert any(LINK.search(cell) for cell in input_cells)

    def test_personal_values_are_reserved_examples(
        self, input_cells: list[str]
    ) -> None:
        """Every email, IP and link uses a reserved example name or range.

        example.org is reserved by RFC 2606 and 192.0.2.0/24 by RFC 5737,
        so these values can never reach a real person or site.
        """
        for cell in input_cells:
            for email in EMAIL.findall(cell):
                assert email.endswith("@example.org"), email
            for ip in IP.findall(cell):
                assert ip.startswith("192.0.2."), ip
            for site in re.findall(r"https?://([^/\s]+)", cell):
                assert site == "example.org", site


class TestUnpivotSurvey:
    """``unpivot_survey``: the wide export becomes one row per answer."""

    def test_free_text_stays_out(
        self, unpivoted: tuple[pd.DataFrame, pd.DataFrame]
    ) -> None:
        """Text typed into an Other box is neither an answer nor kept."""
        answers, other_text = unpivoted
        assert "my free text" not in set(answers["answer"])
        assert other_text.empty

    def test_ticked_boxes_give_the_mapped_option(
        self, unpivoted: tuple[pd.DataFrame, pd.DataFrame]
    ) -> None:
        """Any value in a tick-box column is the option from the mapping."""
        answers, _ = unpivoted
        r1 = answers[answers["response_id"] == "R1"]
        q04 = set(r1.loc[r1["question_id"] == "Q04", "answer"])
        assert q04 == {"Minor illness", "Mental health", "Other"}

    def test_welsh_answer_is_translated(
        self, unpivoted: tuple[pd.DataFrame, pd.DataFrame]
    ) -> None:
        """Weithiau is recorded as the English answer Sometimes."""
        answers, _ = unpivoted
        q14 = answers[answers["question_id"] == "Q14"]
        assert list(q14["answer"]) == ["Yes", "Sometimes", "No"]

    @pytest.mark.parametrize(
        ("role", "qid", "option"),
        [("tci k", "Q01", "A"), ("tick", "", "A"), ("tick", "Q01", "")],
    )
    def test_rejects_invalid_mapping(
        self, role: str, qid: str, option: str
    ) -> None:
        """Reject mapping typos rather than silently dropping answers.

        Args:
            role: Mapping role, possibly misspelt.
            qid: Question identifier, possibly blank.
            option: Tick option, possibly blank.
        """
        specs = pd.DataFrame(
            [["A", role, qid, option]],
            columns=wrangle.MAPPING_COLUMNS["survey_columns"],
        )
        with pytest.raises(wrangle.InputError, match="survey_columns.csv"):
            wrangle.unpivot_survey(
                pd.DataFrame({"response_id": ["R1"], "A": ["yes"]}),
                specs,
                {},
                {},
                False,
            )

    def test_tick_uses_catalogue_answer_case(self) -> None:
        """Case differences in tick labels cannot break catalogue links."""
        specs = pd.DataFrame(
            [["A", "tick", "Q01", "yes"]],
            columns=wrangle.MAPPING_COLUMNS["survey_columns"],
        )
        answers, _, _ = wrangle.unpivot_survey(
            pd.DataFrame({"response_id": ["R1"], "A": ["tick"]}),
            specs,
            {("Q01", "yes"): "Yes"},
            {},
            False,
        )
        assert list(answers["answer"]) == ["Yes"]


class TestSurveyPercentages:
    """``survey_percentages``: Figure 13 numbers for one question."""

    def test_percent_is_ticks_over_respondents(
        self, unpivoted: tuple[pd.DataFrame, pd.DataFrame]
    ) -> None:
        """Percent = ticks / people who answered the question.

        R3 ticked nothing for Q04, so only R1 and R2 count as
        respondents.
        """
        answers, _ = unpivoted
        q4 = wrangle.survey_percentages(answers, "Q04").set_index("answer")
        assert (q4["respondents"] == 2).all()
        assert q4.loc["Minor illness", "ticks"] == 2
        assert q4.loc["Minor illness", "percent"] == pytest.approx(100.0)
        assert q4.loc["Mental health", "percent"] == pytest.approx(50.0)
        assert q4.loc["Other", "percent"] == pytest.approx(50.0)
        assert (q4["percent"] == q4["ticks"] / q4["respondents"] * 100).all()

    def test_single_choice_counts_everyone_who_answered(
        self, unpivoted: tuple[pd.DataFrame, pd.DataFrame]
    ) -> None:
        """All three responses answered Q14; one chose Sometimes."""
        answers, _ = unpivoted
        q14 = wrangle.survey_percentages(answers, "Q14").set_index("answer")
        assert q14.loc["Sometimes", "ticks"] == 1
        assert q14["respondents"].iloc[0] == 3


class TestCountValues:
    """``count_values``: counts in an order that every pandas gives."""

    def test_most_common_first_then_order_of_appearance(self) -> None:
        """Tied counts keep the order in which the values first appear."""
        values = pd.Series(["b", "c", "a", "c", "a", "b", "d", "c"])
        counts = wrangle.count_values(values)
        assert list(counts.items()) == [("c", 3), ("b", 2), ("a", 2), ("d", 1)]

    def test_blanks_are_not_counted(self) -> None:
        """Missing values are left out, as value_counts leaves them out."""
        values = pd.Series(["x", None, "x", float("nan")], dtype=object)
        assert list(wrangle.count_values(values).items()) == [("x", 2)]


class TestParseFlag:
    """``parse_flag``: 'Y (Dec)' style text on Account signups."""

    @pytest.mark.parametrize(
        ("text", "signup_month", "flag", "dates"),
        [
            ("", date(2025, 11, 1), False, []),
            ("Y", date(2025, 11, 1), True, []),
            ("\nY (Dec)", date(2025, 11, 1), True, [date(2025, 12, 1)]),
            ("Y (Dec)", date(2026, 1, 1), True, [date(2025, 12, 1)]),
            ("Y (Jan)", date(2025, 12, 1), True, [date(2026, 1, 1)]),
            (
                "Y (Nov 25 & Aug 26)",
                date(2025, 11, 1),
                True,
                [date(2025, 11, 1), date(2026, 8, 1)],
            ),
            ("Y (March 2026)", date(2026, 2, 1), True, [date(2026, 3, 1)]),
            ("Y (Sept 26)", date(2026, 7, 1), True, [date(2026, 9, 1)]),
            ("maybe", date(2026, 7, 1), None, []),
        ],
    )
    def test_reads_flag_and_dates(
        self,
        text: str,
        signup_month: date,
        flag: bool | None,
        dates: list[date],
    ) -> None:
        """The text gives a flag and first-of-month dates.

        A month without a year gets the year closest to the sign-up
        month.

        Args:
            text: The cell text.
            signup_month: The row's sign-up month.
            flag: The expected flag (None when unreadable).
            dates: The expected dates.
        """
        got_flag, got_dates, _ = wrangle.parse_flag(text, signup_month)
        assert got_flag == flag
        assert got_dates == dates


class TestCleanText:
    """``clean_text``: any cell becomes tidy text."""

    def test_numbers_and_text_of_one_value_match(self) -> None:
        """1, '1' and 1.0 all become '1', so lookups match them."""
        assert (
            wrangle.clean_text(1)
            == wrangle.clean_text("1")
            == wrangle.clean_text(1.0)
            == "1"
        )

    def test_stray_newlines_and_excel_codes_go(self) -> None:
        """Newlines and Excel's _x000D_ become single spaces, trimmed."""
        assert wrangle.clean_text("\n2-5") == "2-5"
        assert wrangle.clean_text("Sleep_x000D_\nGambling") == "Sleep Gambling"

    def test_blanks_become_empty_text(self) -> None:
        """None and NaN both become ''."""
        assert (
            wrangle.clean_text(None) == wrangle.clean_text(float("nan")) == ""
        )


class TestToDate:
    """Read Excel and text dates without ambiguity."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("2026-03-04", date(2026, 3, 4)),
            ("04/03/2026", date(2026, 3, 4)),
            (46085, date(2026, 3, 4)),
            (46085.5, date(2026, 3, 4)),
            (pd.NaT, None),
            (pd.NA, None),
            (True, None),
            (float("inf"), None),
            ("2026-02-30", None),
            ("", None),
        ],
    )
    def test_cell_types(self, value: object, expected: date | None) -> None:
        """Read supported dates and reject missing or invalid values.

        Args:
            value: An Excel cell or text date.
            expected: The exact calendar date, or no date.
        """
        assert wrangle.to_date(value) == expected


class TestAttachEmployerIds:
    """Attach employer keys even when a source contains no records."""

    def test_empty_frame_has_key_column(self) -> None:
        """Downstream joins require the key on header-only sources."""
        frame = pd.DataFrame(columns=["org"])
        dim = pd.DataFrame(columns=wrangle.COLUMNS["dim_employer"])
        wrangle.attach_employer_ids([frame], dim)
        assert list(frame.columns) == ["org", "employer_id"]
        assert frame.empty


class TestMakeUnique:
    """Repeated Excel headers remain unique beside literal suffixes."""

    def test_reserves_existing_suffixes(self) -> None:
        """Generated names cannot overwrite an existing suffixed column."""
        assert wrangle.make_unique(["A", "A", "A.1", "A"]) == [
            "A",
            "A.2",
            "A.1",
            "A.3",
        ]


class TestWriteOutputs:
    """A failed generation preserves the last complete output set."""

    @pytest.mark.parametrize("failure", ["csv", "report", "publish"])
    def test_failure_keeps_previous_generation(
        self,
        tmp_path: Path,
        run_time: datetime,
        monkeypatch: pytest.MonkeyPatch,
        failure: str,
    ) -> None:
        """Inject failures in rendering and publication.

        Args:
            tmp_path: Temporary output location.
            run_time: Frozen pipeline clock.
            monkeypatch: Scoped failure injection.
            failure: Stage at which the run fails.
        """
        out = tmp_path / "out"
        out.mkdir()
        for name in (
            "badges.csv",
            "fact_event.csv",
            "data_quality_report.md",
            "survey_other_text.csv",
            "notes.txt",
        ):
            (out / name).write_text("old " + name, encoding="utf-8")
        before = {p.name: p.read_bytes() for p in out.iterdir()}
        tables = {
            "badges": pd.DataFrame({"badge": ["new"]}),
            "fact_event": pd.DataFrame(columns=wrangle.COLUMNS["fact_event"]),
        }
        original = wrangle.write_csv
        rename = Path.rename

        def write(df: pd.DataFrame, folder: Path, name: str) -> int:
            """Fail while writing the second table.

            Args:
                df: Output frame.
                folder: Staging folder.
                name: Table to write.

            Returns:
                Number of rows if successful.
            """
            if name == "fact_event":
                raise OSError("disk full")
            return original(df, folder, name)

        def fail_report(
            self: wrangle.Report, path: Path, run_at: datetime
        ) -> None:
            """Simulate a report write failure.

            Args:
                self: Report being rendered.
                path: Staged report path.
                run_at: Frozen run timestamp.
            """
            raise OSError("disk full")

        def fail_publish(self: Path, target: str | Path) -> Path:
            """Fail only when installing the staged generation.

            Args:
                self: Directory being renamed.
                target: Destination directory.

            Returns:
                The renamed path when restoring the old generation.
            """
            if self.name == "tables":
                raise OSError("publish failed")
            return rename(self, target)

        if failure == "csv":
            monkeypatch.setattr(wrangle, "write_csv", write)
        elif failure == "report":
            monkeypatch.setattr(wrangle.Report, "write", fail_report)
        else:
            monkeypatch.setattr(Path, "rename", fail_publish)
        report = wrangle.Report()
        with pytest.raises(OSError):
            wrangle.write_outputs(
                tables, out, pd.DataFrame({"event_type": []}), report, run_time
            )
        assert {p.name: p.read_bytes() for p in out.iterdir()} == before
        assert list(tables["badges"].columns) == ["badge"]
        assert not report.sections["Outputs"]


class TestWriteCsv:
    """Output schema filtering also checks retained values for identifiers."""

    @pytest.mark.parametrize(
        "value", ["person@example.org", "192.0.2.4", "https://example.org/p"]
    )
    def test_blocks_personal_values(self, tmp_path: Path, value: str) -> None:
        """Stop personal text pasted into a retained output field.

        Args:
            tmp_path: Temporary output folder.
            value: Reserved synthetic personal identifier.
        """
        with pytest.raises(wrangle.InputError, match="badges.csv") as error:
            wrangle.write_csv(
                pd.DataFrame({"badge": [value]}), tmp_path, "badges"
            )
        assert value not in str(error.value)
        assert not (tmp_path / "badges.csv").exists()


class TestReport:
    """Reports must not leak personal text through warnings."""

    def test_blocks_personal_values(
        self, tmp_path: Path, run_time: datetime
    ) -> None:
        """Reject identifiers in report notes without echoing them."""
        report = wrangle.Report()
        report.add("Warnings", "bad value person@example.org")
        path = tmp_path / "data_quality_report.md"
        with pytest.raises(wrangle.InputError, match="data_quality_report.md"):
            report.write(path, run_time)
        assert not path.exists()

    def test_repeated_write_is_identical(
        self, tmp_path: Path, run_time: datetime
    ) -> None:
        """Rendering a report twice must not duplicate unmapped notes."""
        report = wrangle.Report()
        report.unmapped[("sector", "signups", "New band")] = 2
        path = tmp_path / "report.md"
        report.write(path, run_time)
        first = path.read_bytes()
        report.write(path, run_time)
        assert path.read_bytes() == first
        assert report.sections["Unmapped values"] == []


class TestBuildQuestionCatalogue:
    """Catalogue keys must not drop or multiply survey answers."""

    @pytest.mark.parametrize("problem", ["unknown", "questions", "options"])
    def test_rejects_invalid_keys(self, tmp_path: Path, problem: str) -> None:
        """Reject orphan and duplicate catalogue keys before joining.

        Args:
            tmp_path: Temporary mapping folder.
            problem: Mapping defect to introduce.
        """
        question = "Q01,Question,Short,single\n"
        option = "Q01,Yes,Yes,1\n"
        (tmp_path / "survey_questions.csv").write_text(
            "question_id,question,question_short,question_type\n"
            + question
            + (question if problem == "questions" else ""),
            encoding="utf-8",
        )
        (tmp_path / "survey_answers.csv").write_text(
            "question_id,answer,answer_short,answer_order\n"
            + option
            + (option if problem == "options" else ""),
            encoding="utf-8",
        )
        specs = pd.DataFrame(
            [
                [
                    "Choice",
                    "tick",
                    "Q99" if problem == "unknown" else "Q01",
                    "Yes",
                ]
            ],
            columns=wrangle.MAPPING_COLUMNS["survey_columns"],
        )
        answers = pd.DataFrame(columns=["question_id", "answer"])
        with pytest.raises(wrangle.InputError, match="survey_.*csv"):
            wrangle.build_question_catalogue(tmp_path, specs, answers)
