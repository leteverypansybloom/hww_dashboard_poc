"""Outputs must agree across processes and hash seeds."""

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from hww_dashboard import wrangle


class TestRun:
    """``run`` produces reproducible tables and reports."""

    def test_repeated_runs(
        self, tmp_path: Path, fixture_config: Path, run_time: datetime
    ) -> None:
        """Two runs at one reference time give the same published bytes.

        Args:
            tmp_path: Isolated output directories.
            fixture_config: Synthetic inputs and settings.
            run_time: Fixed analysis time.
        """
        first, second = tmp_path / "first", tmp_path / "second"
        for out in (first, second):
            wrangle.run(fixture_config, out, run_time, run_id="repeat")
        for path in first.iterdir():
            # Records include completion times and describe the execution.
            if path.name != "run_record.json":
                assert path.read_bytes() == (second / path.name).read_bytes()
                assert b"\r\n" not in path.read_bytes()

    def test_hash_seeds(
        self, tmp_path: Path, fixture_config: Path, run_time: datetime
    ) -> None:
        """Independent processes with different hash seeds agree.

        Args:
            tmp_path: Isolated output directories.
            fixture_config: Synthetic inputs and settings.
            run_time: Fixed analysis time.
        """
        code = (
            "import sys; from datetime import datetime; "
            "from hww_dashboard.wrangle import run; "
            "run(sys.argv[1], sys.argv[2], "
            "datetime.fromisoformat(sys.argv[3]), run_id='hash-seed')"
        )
        folders = [tmp_path / "seed1", tmp_path / "seed77"]
        for seed, folder in zip(("1", "77"), folders, strict=True):
            env = {**os.environ, "PYTHONHASHSEED": seed}
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    code,
                    str(fixture_config),
                    str(folder),
                    run_time.isoformat(),
                ],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            assert result.returncode == 0, result.stderr
        for path in folders[0].iterdir():
            if path.name != "run_record.json":
                assert (
                    path.read_bytes() == (folders[1] / path.name).read_bytes()
                )
