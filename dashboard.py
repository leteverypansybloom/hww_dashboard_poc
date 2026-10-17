"""Start the HWW dashboard: ``streamlit run dashboard.py``.

Run it from this folder, so Streamlit finds the theme in
.streamlit/config.toml. The app reads the CSVs in output/ next to this
file, or the folder named by the HWW_OUTPUT environment variable. The
app itself is :mod:`hww_dashboard.dashboard`; Streamlit runs this
launcher again on every interaction.
"""

from pathlib import Path

from hww_dashboard.dashboard import main

main(Path(__file__).resolve().parent)
