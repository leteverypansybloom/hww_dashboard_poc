# Notes for coding agents

Everything in `CONTRIBUTING.md` applies. The points agents most often
need:

- **Environment.** The project venv is `.venv` in this folder
  (`pip install -e ".[dev]"`). On Windows, keep any venv in a short
  path; Streamlit fails to install in long paths (WinError 206).
- **Before every commit**, run `black --check .`, `ruff check .`,
  `mypy`, `python -m pytest -W error` and
  `git diff --exit-code -- tests/golden`.
- **Golden files.** Never change `tests/golden/` to make a test pass.
  An output change needs the project owner's approval first.
- **Test data.** Tests use the synthetic inputs in `tests/data/` and a
  fixed run time. Don't add real data, and don't read files outside
  the repository.
- **Out of scope unless asked**: the dashboard files listed in
  `CONTRIBUTING.md`. Their tests must keep passing.
- **Records.** Add an entry to `DECISIONS_en.md` for each design
  decision, and update the docs in the same commit.
- **Git.** One commit per logical change. Don't push or merge unless
  asked.
- **Messages.** Error messages say what to fix, in plain language, and
  never quote cell values.
