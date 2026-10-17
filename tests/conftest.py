"""Shared fixtures: the synthetic inputs, the frozen config and one run.

The inputs in tests/data/inputs/ are synthetic copies of the dummy HWW
workbooks (see tests/data/README.md). These fixtures point every test at
them with the clock fixed, so the tests read nothing outside the project
and give the same results on any day.
"""

from datetime import date, datetime
from pathlib import Path

import pytest

from hww_dashboard import wrangle

TESTS = Path(__file__).resolve().parent


@pytest.fixture(scope="session")
def project_folder() -> Path:
    """The project folder, which holds the launchers and config.toml.

    Returns:
        The folder above tests/.
    """
    return TESTS.parent


@pytest.fixture(scope="session")
def data_folder() -> Path:
    """The folder of synthetic inputs and the config that reads them.

    Returns:
        tests/data/.
    """
    return TESTS / "data"


@pytest.fixture(scope="session")
def fixture_config(data_folder: Path) -> Path:
    """The frozen config that reads the synthetic inputs.

    Returns:
        tests/data/config.toml.
    """
    return data_folder / "config.toml"


@pytest.fixture(scope="session")
def run_time() -> datetime:
    """The time that pipeline runs in the tests treat as now.

    Returns:
        12:00 on 10 October 2026, the day the pipeline guide's examples
        use. The golden data quality report was written at this time.
    """
    return datetime(2026, 10, 10, 12, 0)


@pytest.fixture(scope="session")
def today(run_time: datetime) -> date:
    """The date that the tests treat as today.

    Returns:
        The day of ``run_time``.
    """
    return run_time.date()


@pytest.fixture(scope="session")
def pipeline_output(
    tmp_path_factory: pytest.TempPathFactory,
    fixture_config: Path,
    run_time: datetime,
) -> Path:
    """Run the whole pipeline once on the synthetic inputs.

    The folder is shared by every test that uses this fixture, so tests
    must copy it before changing anything in it.

    Returns:
        The folder holding the tables and data_quality_report.md.
    """
    folder = tmp_path_factory.mktemp("pipeline_output")
    wrangle.run(fixture_config, output_folder=folder, now=run_time)
    return folder
