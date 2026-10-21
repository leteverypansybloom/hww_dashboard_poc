"""Checks on what the scheduled job in GCP runs.

The image (Dockerfile) runs ``hww-run /app/config.gcp.toml``. These
tests check that config matches config.toml apart from where things
are, that hww-run stops when ingestion fails, and that the commands
the package installs point at real functions.
"""

import tomllib
from pathlib import Path
from typing import Any

import pytest

from hww_dashboard import job, serve, wrangle

#: Sections that say where things are, so may differ between configs.
LOCATIONS = ("paths", "output", "landed")

#: Environment variables config.gcp.toml reads.
GCP_VARIABLES = (
    "HWW_BQ_PROJECT",
    "HWW_BQ_DATASET",
    "HWW_GCP_PROJECT",
    "HWW_LANDING_BUCKET",
    "HWW_STORE_BUCKET",
    "HWW_LANDED_DATASET",
)


def read(path: Path) -> dict[str, Any]:
    """Parse a TOML file.

    Args:
        path: The file.

    Returns:
        Its contents.
    """
    with open(path, "rb") as f:
        return tomllib.load(f)


class TestGcpConfig:
    """config.gcp.toml, which the image runs with."""

    def test_rules_match_config_toml(self, project_folder: Path) -> None:
        """Every column and rule setting is the same as config.toml's.

        Args:
            project_folder: The project folder.
        """
        shipped = read(project_folder / "config.toml")
        gcp = read(project_folder / "config.gcp.toml")
        for section in LOCATIONS:
            shipped.pop(section, None)
            gcp.pop(section, None)
        assert gcp == shipped

    def test_passes_the_checks(
        self, project_folder: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With its environment variables set, the config is valid.

        Args:
            project_folder: The project folder.
            monkeypatch: Sets the environment variables.
        """
        for name in GCP_VARIABLES:
            monkeypatch.setenv(name, f"test-{name.lower()}")
        cfg = wrangle.load_config(project_folder / "config.gcp.toml")
        assert cfg["landed"]["read"] is True
        assert cfg["landed"]["target"] == "gcp"
        assert cfg["output"]["target"] == "bigquery"

    def test_names_every_variable_it_uses(self, project_folder: Path) -> None:
        """The variables listed here are the ones the config uses.

        Args:
            project_folder: The project folder.
        """
        lines = (project_folder / "config.gcp.toml").read_text("utf-8")
        # Comments mention ${NAME} as an example; only settings count.
        settings = [line.split("#", 1)[0] for line in lines.splitlines()]
        used = set(wrangle.CONFIG_VARIABLE.findall(" ".join(settings)))
        assert used == set(GCP_VARIABLES)


class TestJob:
    """hww-run: ingestion, then the pipeline only if it succeeded."""

    def test_pipeline_runs_after_ingestion(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both run, with the same config, and the pipeline's code returns.

        Args:
            monkeypatch: Replaces the two steps.
        """
        calls: list[tuple[str, list[str]]] = []

        def ingest(argv: list[str]) -> int:
            """Record the ingestion call and succeed.

            Args:
                argv: The arguments it was given.

            Returns:
                0, for success.
            """
            calls.append(("ingest", argv))
            return 0

        def pipeline(argv: list[str]) -> int:
            """Record the pipeline call and succeed.

            Args:
                argv: The arguments it was given.

            Returns:
                0, for success.
            """
            calls.append(("wrangle", argv))
            return 0

        monkeypatch.setattr("hww_dashboard.job.landing.main", ingest)
        monkeypatch.setattr("hww_dashboard.job.wrangle.main", pipeline)

        assert job.main(["my.toml"]) == 0
        assert calls == [("ingest", ["my.toml"]), ("wrangle", ["my.toml"])]

    def test_failed_ingestion_stops_the_pipeline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failed ingestion's code is returned and the tables are kept.

        Args:
            monkeypatch: Replaces the two steps.
        """
        ran: list[str] = []

        def pipeline(argv: list[str]) -> int:
            """Record that the pipeline ran.

            Args:
                argv: The arguments it was given.

            Returns:
                0, for success.
            """
            ran.append("wrangle")
            return 0

        monkeypatch.setattr("hww_dashboard.job.landing.main", lambda argv: 1)
        monkeypatch.setattr("hww_dashboard.job.wrangle.main", pipeline)

        assert job.main([]) == 1
        assert ran == []


class TestServe:
    """hww-dashboard starts Streamlit on the packaged app."""

    def test_runs_streamlit_on_the_app(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The command is streamlit run <app.py>, with extra arguments.

        Args:
            monkeypatch: Replaces subprocess.call.
        """
        seen: list[list[str]] = []

        def call(command: list[str]) -> int:
            """Record the command instead of running it.

            Args:
                command: The command line.

            Returns:
                0, for success.
            """
            seen.append(command)
            return 0

        monkeypatch.setattr("hww_dashboard.serve.subprocess.call", call)

        assert serve.main(["--server.port", "8502"]) == 0
        (command,) = seen
        assert command[1:4] == ["-m", "streamlit", "run"]
        assert command[4].endswith("app.py") and Path(command[4]).exists()
        assert command[5:] == ["--server.port", "8502"]


class TestPackaging:
    """The installed commands and the image agree with the code."""

    def test_scripts_point_at_main_functions(
        self, project_folder: Path
    ) -> None:
        """Each [project.scripts] entry names a module's main().

        Args:
            project_folder: The project folder.
        """
        scripts = read(project_folder / "pyproject.toml")["project"]["scripts"]
        assert set(scripts) == {
            "hww-ingest",
            "hww-wrangle",
            "hww-run",
            "hww-dashboard",
        }
        for target in scripts.values():
            module, function = target.split(":")
            assert callable(
                getattr(__import__(module, fromlist=["x"]), function)
            )

    def test_image_runs_the_job_on_the_gcp_config(
        self, project_folder: Path
    ) -> None:
        """The Dockerfile copies and runs config.gcp.toml.

        Args:
            project_folder: The project folder.
        """
        dockerfile = (project_folder / "Dockerfile").read_text("utf-8")
        ignore = (project_folder / ".dockerignore").read_text("utf-8")
        assert 'CMD ["hww-run", "/app/config.gcp.toml"]' in dockerfile
        for needed in ("config.gcp.toml", "mappings/", "src/"):
            assert f"!{needed}" in ignore
