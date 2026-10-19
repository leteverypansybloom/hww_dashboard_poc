"""Hand-worked scenarios: the pipeline against tables worked out by hand.

tests/scenarios/workbooks.py builds four tiny workbooks, each row chosen
to exercise a rule in docs/rules.md. tests/scenarios/expected/ holds the
tables those rules should produce, worked out by hand from the rules
and never copied from the pipeline's output (tests/scenarios/README.md).
The golden snapshot guards against unintended change; these guard the
rules themselves, and the Dataform models can be checked against the
same files.
"""

import importlib.util
import shutil
from datetime import date, datetime
from pathlib import Path
from types import ModuleType

import pandas as pd
import pytest

from hww_dashboard import dashboard_data as dd
from hww_dashboard import wrangle

SCENARIOS = Path(__file__).resolve().parent / "scenarios"
EXPECTED = SCENARIOS / "expected"
RULES = ("summary_1_sent", "session_1_held", "last_session_held")


def read(path: Path) -> pd.DataFrame:
    """Read a table as text, blanks as ``""``.

    Args:
        path: A CSV file.

    Returns:
        The table.
    """
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def same_rows(actual: pd.DataFrame, expected: pd.DataFrame) -> None:
    """Check two tables hold the same rows, in any order.

    Args:
        actual: The pipeline's table; only the expected columns count.
        expected: The hand-worked table.
    """
    columns = list(expected.columns)
    pd.testing.assert_frame_equal(
        actual[columns].sort_values(columns).reset_index(drop=True),
        expected.sort_values(columns).reset_index(drop=True),
    )


@pytest.fixture(scope="module")
def workbooks() -> ModuleType:
    """Import the scenario builder.

    Returns:
        tests/scenarios/workbooks.py as a module.
    """
    path = SCENARIOS / "workbooks.py"
    spec = importlib.util.spec_from_file_location("scenario_workbooks", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def runs(
    workbooks: ModuleType,
    tmp_path_factory: pytest.TempPathFactory,
    fixture_config: Path,
    project_folder: Path,
    run_time: datetime,
) -> dict[str, Path]:
    """Run the pipeline on the scenario, once per WAS "completed" rule.

    The live mappings are copied and given the scenario's one
    organisation override.

    Args:
        workbooks: The scenario builder.
        tmp_path_factory: Makes the scenario's folders.
        fixture_config: The frozen config, copied for each rule.
        project_folder: Holds the live mappings.
        run_time: The tests' fixed run time.

    Returns:
        Completed rule -> the folder its run wrote.
    """
    root = tmp_path_factory.mktemp("scenario")
    inputs = root / "inputs"
    workbooks.write(inputs)
    maps = root / "mappings"
    shutil.copytree(project_folder / "mappings", maps)
    raw, canonical = workbooks.OVERRIDE
    (maps / "org_overrides.csv").write_text(
        f"raw_name,canonical_name\n{raw},{canonical}\n", "utf-8"
    )
    text = (
        fixture_config.read_text("utf-8")
        .replace(
            'input_folder = "inputs"', f'input_folder = "{inputs.as_posix()}"'
        )
        .replace(
            'mappings_folder = "../../mappings"',
            f'mappings_folder = "{maps.as_posix()}"',
        )
    )
    outputs = {}
    for rule in RULES:
        config = root / f"{rule}.toml"
        config.write_text(
            text.replace(
                'completed_rule = "summary_1_sent"',
                f'completed_rule = "{rule}"',
            ),
            "utf-8",
        )
        outputs[rule] = root / rule
        wrangle.run(config, output_folder=outputs[rule], now=run_time)
    return outputs


class TestRun:
    """``run`` on the scenario workbooks gives the hand-worked tables."""

    @pytest.mark.parametrize(
        "table",
        [
            "dim_employer",
            "fact_signup",
            "dim_survey_response",
            "fact_survey_answer",
            "fact_was_session",
            "fact_was_session_topic",
            "fact_engagement",
        ],
    )
    def test_table_matches_the_hand_worked_one(
        self, runs: dict[str, Path], table: str
    ) -> None:
        """Each table holds exactly the rows the rules give.

        Args:
            runs: The scenario's output folders.
            table: A table with an expected file.
        """
        actual = read(runs["summary_1_sent"] / f"{table}.csv")
        same_rows(actual, read(EXPECTED / f"{table}.csv"))

    @pytest.mark.parametrize("rule", ["session_1_held", "last_session_held"])
    def test_other_completed_rules(
        self, runs: dict[str, Path], rule: str
    ) -> None:
        """Each "completed" rule dates WAS completions its own way.

        Args:
            runs: The scenario's output folders.
            rule: The rule the run used.
        """
        events = read(runs[rule] / "fact_engagement.csv")
        completed = events[events["event_type"] == "was_completed"]
        same_rows(completed, read(EXPECTED / f"was_completed_{rule}.csv"))

    def test_figure_13_percentages(self, runs: dict[str, Path]) -> None:
        """Percent is ticks over respondents to that question (R36).

        Two responses answered Q04 and three answered Q14, so a single
        tick is 50% of Q04 and a third of Q14. The numbers are worked
        out as the dashboard shows them, over every date and with no
        filters; options nobody chose are left out.

        Args:
            runs: The scenario's output folders.
        """
        tables = dd.load_tables(runs["summary_1_sent"])
        start, end = date(2000, 1, 1), date(2099, 12, 31)
        q04, respondents = dd.survey_question_results(
            tables, "Q04", start, end, {}
        )
        assert respondents == 2
        q04 = q04[q04["ticks"] > 0].set_index("answer")
        assert q04["percent"].to_dict() == {
            "Fatigue or burnout": 100.0,
            "Other": 50.0,
            "Headaches and migraines": 50.0,
        }
        q14, respondents = dd.survey_question_results(
            tables, "Q14", start, end, {}
        )
        assert respondents == 3
        q14 = q14[q14["ticks"] > 0]
        assert q14["percent"].tolist() == pytest.approx([100 / 3] * 3)
