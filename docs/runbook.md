# Running and supporting the HWW pipeline

The operator owns each run; the data owner decides whether the results are fit
for reporting. The current output is a complete snapshot of cumulative inputs.

## Before a run

1. Use an approved machine or the configured Cloud Run job. Complete the DPIA
   and agree access and retention before loading real data.
2. Keep original workbooks outside this repository. Check all four sources
   belong to the reporting period. The job does not provide a consistent
   snapshot while someone replaces its inputs; finish uploads before starting.
3. Use a local config (for example `config.local.toml`, ignored by git).
   Paths are relative to that file. Copy `config.toml`, retaining its column
   settings, and change the paths, file names and output settings.
4. For GCP use a fixed survey file name, matching py-common's contract, rather
   than the laptop's dated pattern. Agree whether the survey export or the
   monitoring workbook is the source of truth before deployment.

## Run on Windows

Activate the project venv and install the pinned dependencies:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt -c constraints.txt
python wrangle.py config.local.toml
$LASTEXITCODE
```

For a demo use `python wrangle.py tests/data/config.toml`. This uses synthetic
inputs and replaces the local `output/` folder. The dashboard currently reads
CSV files; its owners must add BigQuery reading before using the cloud tables.

## Act on the result

| Exit | Meaning | Action |
|---|---|---|
| 0 | Outputs published | Read **Needs attention**, including warnings about fewer rows. Get the data owner's agreement before reporting. |
| 1 | Input, configuration or access problem | Follow the message, correct the source or setting, then rerun. |
| 2 | Unexpected failure | Give support the run id, commit and error location. Inspect protected logs; avoid copying raw data into tickets. |

A successful run with warnings still exits 0. In folder mode the report is
`output/data_quality_report.md`; the run record is `output/run_record.json`.
Logs are beside the config in `logs/`, with the newest 20 retained. In BigQuery,
read the one row in `data_quality_report`; `runs` contains the run records.

Unmapped labels need an agreed mapping. Changed survey headings need a reviewed
mapping change. Empty sources stop the run unless that source explicitly sets
`allow_empty = true`. A fall greater than `[checks] max_row_drop` (default
0.1) requires investigation, even when the run succeeds. Never suppress a
warning just to make a report look clean.

The report's Duplicates section lists employers that are possibly one
organisation (names that differ only by punctuation, `&` or a word like
Ltd). They are not counted under Needs attention. Check each pair, and add
an override to `mappings/org_overrides.csv` only for those that are one
organisation; the others stay listed.

## Recovery

Correct the source and rerun the complete pipeline. BigQuery stages the new
rows and replaces final rows in one transaction. A failed transaction keeps
the previous rows. A timeout can have an uncertain outcome: inspect the job id
and latest `runs` record before retrying. Stop overlapping jobs first.

Folder publication restores the previous folder on ordinary errors. A process
killed during renaming can leave a `.hww-*` sibling with `previous/`; stop all
readers and writers and ask support to recover it. Keep the backup until its
contents are checked. This operation is not safe against power loss or readers
opening files during the rename gap.

For an incorrect successful run, restore the approved source versions and rerun
with the recorded config, mappings and code. Do not edit output tables by hand.
Agree retention and deletion with the data owner; BigQuery time travel and
fail-safe also retain replaced rows.

## Support ownership

Before scheduling, name a primary and backup operator, data owner, alert
recipient and expected arrival date for each source. Test a failed-run alert,
a warning alert and a missing-run alert. A report with no warnings is not proof
that the latest data arrived. Review the freshness of every source separately.
