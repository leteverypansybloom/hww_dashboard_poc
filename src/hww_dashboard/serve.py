"""``hww-dashboard``: start the Streamlit dashboard.

Run it from the project folder, so the app finds ``output/`` and
Streamlit finds the theme in ``.streamlit/config.toml``. Extra
arguments go to ``streamlit run``, e.g. ``hww-dashboard --server.port
8502``.
"""

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

APP = Path(__file__).resolve().with_name("app.py")


def main(argv: Sequence[str] | None = None) -> int:
    """Run ``streamlit run`` on the dashboard app.

    Args:
        argv: Extra arguments for ``streamlit run`` (defaults to
            sys.argv[1:]).

    Returns:
        Streamlit's exit code.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    command = [sys.executable, "-m", "streamlit", "run", str(APP), *args]
    return subprocess.call(command)


if __name__ == "__main__":
    sys.exit(main())
