# Design Decisions

When project decisions are made they can be added to the decision log.
This records the thinking as the project evolves. Focus on recording
decisions which someone joining the project might need to know.

Order in reverse chronological order (most recent at top).

Entries are not rewritten once made. When a decision changes, add a
new dated entry saying which earlier entry it replaces, and mark the
earlier entry as superseded.

The format is the one py-common uses (`DECISIONS_en.md` in that
repository).

## 2026-10-18 — Production readiness

The production-readiness review prepared the prototype for two jobs:
running on real data until the Dataform models exist, and being the
reference those models are checked against. Development runs on
Windows laptops and in GCP; eventually everything runs in GCP.

### Until Dataform exists, the pipeline writes its tables to BigQuery

The CSV tables were a stand-in for BigQuery tables. Until the Dataform
models exist, this pipeline loads its tables into an interim BigQuery
dataset itself, with the table names and schemas the Dataform models
are expected to produce. Power BI and the dashboard can then move to
Dataform's tables by changing the dataset name. Laptops and tests keep
writing CSV files.

Not chosen: keeping CSV files until Dataform replaces them. Nothing
could report from BigQuery in the meantime, and real data would sit
in CSV files on laptops and in buckets rather than behind dataset
permissions.

**Trade-off**: a BigQuery client dependency, and a writer to maintain
for an interim period. Benefit: consumers are built on BigQuery from
the start, and comparing this pipeline with Dataform is a SQL query
within one warehouse.

### The golden snapshot is refreshed by a script, never by a test

The code-quality review made the golden test read-only, which left no
documented way to update the snapshot after an agreed output change.
`scripts/refresh_golden.py` does it on purpose: it runs the pipeline
on the synthetic inputs at the tests' fixed time, rewrites only the
files that differ and lists them.

Not chosen: bringing back the environment switch that made the test
rewrite the snapshot. A test that can change its own expected values
can hide a mistake.

**Trade-off**: one more file to keep. Benefit: refreshing is a
separate, visible step that someone chooses to take.

### The output folder is not kept in git

`output/` was committed so the dashboard ran straight after cloning.
With real data, the next `git add .` would have committed
organisation names and survey answers, and after a push only a
history rewrite removes them. `output/` is now ignored and untracked.
The committed tables were identical to `tests/golden/`, so nothing is
lost: `python wrangle.py tests/data/config.toml` rebuilds them from
the synthetic inputs (that config's output folder was unused, because
the tests write to temporary folders).

**Trade-off**: a fresh clone needs one command before the dashboard
shows anything. Benefit: real tables can't reach the repository by
accident.

### Installs are pinned by a constraints file, as in py-common

`pyproject.toml` keeps compatible ranges, and `constraints.txt` pins
one tested version of every runtime library for CPython 3.11 to 3.13
on Linux and Windows. Laptops, CI and the GCP image install with
`-c constraints.txt`. numpy is pinned per Python version, because its
newest release no longer supports 3.11.
`scripts/update_constraints.py` regenerates the file with pip's
resolver for every platform, without installing anything. The lower
bounds rose to the oldest versions actually tested (pandas 2.2.3,
openpyxl 3.1.5).

Not chosen: a hashed lock file (pip-tools or uv). It's stronger, but
a different tool from py-common.

### The dashboard and BigQuery libraries are extras

Streamlit and Plotly moved to a `dashboard` extra and the BigQuery
client to a `bigquery` extra, so the pipeline alone needs only pandas
and openpyxl. `requirements.txt` installs both extras for laptops; the
GCP image needs only `bigquery`.

**Trade-off**: one more word in the install command. Benefit: a
smaller image for the scheduled job, with fewer libraries to audit
and patch.

### Quality gates match py-common's, plus Windows and version jobs

Pre-commit hooks run Black, Ruff, mypy, detect-secrets and file checks
as py-common's do, plus a local guard that refuses `output/`, workbooks
outside `tests/data/inputs/` and stray CSV files. mypy runs from the
project venv rather than a hook environment, because it needs
Streamlit, which fails to install in a hook environment's long Windows
path.

CI adds pip-audit (on the installed set and on `constraints.txt`) and
coverage with a floor of 90% (93% today), and runs on Windows as well
as Linux, because development happens on Windows. Separate jobs test
the oldest and the newest versions the ranges allow; the newest also
runs weekly.

Not chosen: a Codecov upload. The report is kept as a CI artifact
instead, which needs no token or outside service.

### Three exit codes: done, fix something, bug

Exit code 1 used to mean both "fix an input" and "the code crashed",
so a scheduler couldn't tell them apart. Now 0 means the run finished,
1 means a problem a person can fix stopped it, with a message saying
what to do, and 2 means an unexpected error, a bug. An `OSError` while
writing the outputs (a CSV open in Excel, a full disk) counts as 1,
because a person can fix it, and the previous outputs are kept.

Not chosen: a separate code for "finished, but the report needs
attention". A scheduled job would then fail every month over ordinary
data-quality notes; a log line that an alert can match does that job
instead.

### Each run keeps a log; GCP gets JSON lines

The log was bare console text that vanished with the window. Now:

- Console lines carry the time and level, and every run starts with
  its run id.
- In text mode, each run's log is saved as `logs/<run id>.log` next to
  the config (`[paths] log_folder`), with the traceback of any
  unexpected error; the console shows only one line about it. The
  newest 20 logs are kept, and git ignores them.
- `HWW_LOG_FORMAT=json` (for GCP) writes one JSON object per line with
  `severity`, `message` and `run_id`, field names as in py-common's
  JSON logging, and no file. An unexpected error is logged by type and
  stack but not its message, which could quote data.
- The run ends with a WARNING listing what needs attention (unmapped
  values, new or missing survey columns, unknown answers, unreadable
  flags), or an INFO line saying nothing does, so an alert can match
  it.

Not chosen: py-common's `configure_json_logging()`. It would add the
py-common dependency for a few lines of formatting.

### The output contract is one BigQuery schema per table

Types and empty values were implicit in the CSV text, so a comparison
with BigQuery tables would flag differences that aren't real (`true`
against `True`, `NULL` against `""`), and the BigQuery writer had
nothing to type the tables from. Each table now has a schema file in
`src/hww_dashboard/schema/`, in BigQuery's JSON format, with each
column's type, whether it may be empty and what it holds. Every table
is checked in its CSV text form before it is written; a mismatch is a
bug (exit code 2). Dataform can create its tables from the same files,
and `docs/output_contract.md` shows how to compare the two.

The two placeholder tables, `fact_event` and `badges`, have every
column optional until they have a source.

Not chosen: changing the CSV files to BigQuery's style (`true`,
`false`). That would be an output change for no gain, because
BigQuery's CSV loader reads the current style with the schema.

### Job roles and flag text leave fact_signup; phone numbers are refused

`fact_signup` kept each user's job role (free text such as "School
nurse") and the raw text of the two flag columns. With the employer
and the month, a role can identify a person at a small employer, and
nothing used these columns. They are no longer written (data
minimisation); the flags and the dates read from the text remain. The
project owner agreed this output change.

The contact-detail check on every output and the report now refuses UK
phone numbers (0 or +44 and ten more digits) as well as emails, IPv4
addresses and links. `docs/data_protection.md` describes what each
output holds, for the DPIA.

**Trade-off**: anyone who needs roles must ask for them back, with a
DPIA note. Benefit: less personal data in every copy of the outputs.

### Each published output carries a run record

The report gave only the time of a run, so "why did this number
change?" couldn't be answered later. `run_record.json` is now
published with the tables, as the last file in the staged folder. It
records:

- the run id, start and finish times;
- the package version and git commit, and whether there were
  uncommitted changes (`HWW_GIT_COMMIT` supplies the commit in a
  container);
- the Python, pandas, numpy and openpyxl versions;
- the config and every mapping file, with size, time and SHA-256;
- each input file, with its source, sheet, rows read, size, time and
  SHA-256;
- each output's rows and SHA-256, and what needs attention.

It holds no cell values, so it is safe to keep and share, like
py-common's audit records. The report's Inputs lines now name each file
and the first 12 digits of its checksum, which are stable for the same
files, so the golden test still applies. The project owner agreed that
output change.

Not chosen: the report alone. Versions and times change from run to
run, which would make the report differ between identical runs.

### Outputs have LF line endings on every system

pandas and Python wrote CRLF on Windows and LF on Linux, so one run
gave different bytes, and different checksums, on a laptop and in GCP.
The CSV files and the report now always use LF, and `.gitattributes`
keeps text files LF in every working copy. The content is unchanged,
and so are the committed golden files.

## 2026-10-17 — Code-quality review

A line-by-line review of `wrangle.py` (branch `review/code-quality`)
changed what stops a run. These are decisions as well as fixes:

- **More problems stop the run.** Blank or conflicting mapping rows,
  override cycles, invalid survey column mappings, conflicting
  translations, duplicate catalogue keys, duplicate WAS or peer
  participant IDs and an unreadable sign-up month raise `InputError`,
  where they used to produce quietly wrong tables.
- **Outputs are staged, then swapped in.** The whole set is written to
  a temporary folder, which then replaces the output folder; the
  previous folder is restored if that fails.
- **Contact identifiers are refused.** An email address, IPv4 address
  or web link in any output, the report included, stops the run, and
  the message never repeats the value.
- **Dates.** Text in ISO form is read year first, and Excel serial
  numbers are read as dates (1900 epoch).
- **The golden test is read-only.** Tests never rewrite
  `tests/golden/`.

## 2026-10-17 — Package layout

### An installable package with one `wrangle` module

The code is the package `hww_dashboard` in `src/`, so tests and tools
import it like any other library. The pipeline stays one module: it
reads top to bottom in run order, and its stages share the same
helpers, so splitting it would mostly add a "utils" module to jump
to.

**Trade-off**: a long module. Benefit: one place to read the rules
that Dataform will reimplement.

### No py-common in the prototype

py-common lands files in BigQuery for the production route. The
prototype's own reading (a local folder, the newest survey export,
sheets by position, pandas-style column names) doesn't match it, and
using it would change the names in `config.toml` and `mappings/`. An
earlier attempt (branch `py-common-ingestion`) had to wrap py-common
to undo those differences. See `docs/architecture.md`.

### Golden-output test

`tests/test_golden.py` compares every output table and the data
quality report of a run on synthetic inputs, at a fixed time, with
the snapshot in `tests/golden/`. A refactor or dependency upgrade
can't change the numbers without the test failing.

## 2026-10-10 — Prototype design

Recorded on 2026-10-18 from `docs/pipeline_guide.md`, section 8, which
has the reasoning in full.

### Stop on structure, report on values

A missing file, sheet, column, mapping or setting stops the run with
an `InputError` that says what to fix, before anything is written. A
messy value (an unmapped band, a missing date) is handled the same
way every time and listed in the data quality report.

**Trade-off**: the report must be read after every run. Benefit: one
typo doesn't stop the monthly refresh, and nobody misses it either.

### Privacy by allow-list

Only the columns named in `COLUMNS` are written; survey columns with
the `drop` role are never used; free text is off by default.

### Employer ids are hashes of names

`employer_id` is a short MD5 hash of the cleaned, case-folded name,
so it is the same on every run and machine without an id table.

**Trade-off**: renaming an organisation changes its id (an override
keeps the old one), and the id can be reversed by anyone with a list
of names. Benefit: nothing to maintain or lose.

### Exact name matching plus manual overrides

Rows for one organisation merge when their names match after
cleaning and ignoring case, or through `mappings/org_overrides.csv`.
There is no fuzzy matching: a wrong automatic merge is worse than a
visible duplicate.

### The flags on Account signups are not the source of truth

Survey completions come from the survey export and WAS requests from
the WAS database. The hand-typed flags are kept for reconciliation
only, because they disagree with the records in most cases.
