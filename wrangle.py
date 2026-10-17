"""Run the HWW pipeline: ``python wrangle.py [config.toml]``.

With no argument it uses the config.toml next to this file, wherever it
is run from. The pipeline itself is :mod:`hww_dashboard.wrangle`; this
launcher keeps the original command working.
"""

import sys
from pathlib import Path

from hww_dashboard.wrangle import main

if __name__ == "__main__":
    default_config = Path(__file__).resolve().with_name("config.toml")
    sys.exit(main(sys.argv[1:] or [str(default_config)]))
