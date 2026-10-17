"""Healthy Working Wales (HWW) monitoring prototype.

Three modules, used in this order:

- :mod:`hww_dashboard.wrangle` turns the HWW spreadsheets into tidy CSV
  tables and a data quality report (``python wrangle.py``).
- :mod:`hww_dashboard.dashboard_data` loads those tables and does every
  sum the dashboard shows. It has no Streamlit code.
- :mod:`hww_dashboard.dashboard` is the Streamlit app
  (``streamlit run dashboard.py``). It only draws.
"""
