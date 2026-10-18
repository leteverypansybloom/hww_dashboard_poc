# Contributing

How to set up, check and change this project. The same rules apply to
people and to coding agents (`AGENTS.md`).

## Set up

Python 3.11 or newer. On Windows, keep the virtual environment in a
short path: Streamlit's deep package folders fail to install in long
paths (WinError 206).

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt -c constraints.txt
```

`constraints.txt` pins every library to the versions CI tests. To move
to newer versions, run `python scripts/update_constraints.py`, review
the diff, and run the checks.

Then turn on the pre-commit hooks, from the activated venv:

```
pre-commit install
```

Before each commit, git then runs Black, Ruff, mypy, a secrets scan
(`detect-secrets`, against `.secrets.baseline`), file checks, and a
guard that refuses `output/`, workbooks outside `tests/data/inputs/` and
stray CSV files. Run them all by hand with `pre-commit run --all-files`.

## Checks

Run all of these before every commit. CI runs the same checks.

```
black --check .
ruff check .
mypy
python -m pytest -W error
git diff --exit-code -- tests/golden
```

The last one confirms that nothing rewrote the golden files.

On every push and pull request, GitHub Actions runs these checks with
the pinned versions on Python 3.11, 3.12 and 3.13 on Linux and on
Windows. It also audits the dependencies (`pip-audit`, on the installed
set and on `constraints.txt`) and measures coverage, failing below the
`fail_under` figure in `pyproject.toml`. Separate jobs run the tests
with the oldest and the newest versions `pyproject.toml` allows; the
newest also runs every Monday.

## Code standards

- PEP 8 with 79-character lines. Black and Ruff must pass (Ruff rules
  E, W, F, I, N, D with the Google docstring convention, UP and B).
- mypy in strict mode, tests included.
- Google-style docstrings on modules, classes, functions, fixtures and
  test methods.
- No new blanket suppressions: no bare `# noqa`, no `# type: ignore`
  without an error code, no file-wide ignores.

## Tests

- Tests read only synthetic data: `tests/data/` and the files they
  write to temporary folders. Never real workbooks.
- Tests are deterministic: they treat 12:00 on 10 October 2026 as now.
- Tests are grouped in classes named after the function under test.
- A bug fix comes with a test that fails without the fix.

## Golden files

`tests/golden/` holds the output of one run on the synthetic inputs.
It changes only when the project owner has agreed an output change,
and never just to make a failing test pass. The tests never write to
it. After an agreed change:

1. Make the code change.
2. Run `python scripts/refresh_golden.py`. It rewrites only the files
   that differ, and lists them.
3. Check every line of `git diff tests/golden`.
4. Commit the snapshot with the code change, saying in the message
   which output changed and who agreed it.

## Output tables

Each output table has a schema in `src/hww_dashboard/schema/`
(`docs/output_contract.md`). Adding, removing or retyping a column is an
output change: change `COLUMNS` in `wrangle.py` and the schema file
together, and get the project owner's approval.

## Decisions and changes

- Record each design decision in `DECISIONS_en.md`, in its format.
- Keep the docs in step with the code: `README.md`, `docs/` and the
  docstrings.

## Commits and reviews

- One commit per logical change. The summary is under 50 characters,
  in the imperative ("Add ...", "Fix ..."); the body says why.
- Every change reaches `main` through a pull request reviewed by
  someone other than its author. An output change also needs the
  project owner's approval.
- The dashboard files belong to the data scientists:
  `src/hww_dashboard/dashboard.py`, `src/hww_dashboard/dashboard_data.py`,
  `dashboard.py`, `.streamlit/`, `tests/test_dashboard.py` and
  `tests/test_dashboard_data.py`. Changes to them need their review.

## Data protection

- Never commit real data. Real workbooks stay outside the repository,
  and `output/` is ignored by git. To see the dashboard on a fresh
  clone, build the demo tables: `python wrangle.py tests/data/config.toml`.
- Synthetic personal values use reserved examples (`example.org`,
  `192.0.2.x`); `tests/data/README.md` explains how the inputs were
  made.
- Logs and error messages name files, sheets, columns and counts,
  never cell values. The saved run logs in `logs/` may also hold the
  traceback of an unexpected error, so git ignores them, like the
  outputs.
