"""The Streamlit script ``hww-dashboard`` starts.

Streamlit runs this file again on every interaction. The project
folder is the one ``hww-dashboard`` was started from (or
``HWW_PROJECT``), so the app reads that folder's ``output/``.
"""

import os
from pathlib import Path

from hww_dashboard.dashboard import main

main(Path(os.environ.get("HWW_PROJECT", Path.cwd())).resolve())
