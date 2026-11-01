# HWW Dataform models

The SQL that turns py-common's raw tables into the HWW reporting
tables in BigQuery. It is the production version of
`src/hww_dashboard/wrangle.py`: the same rules (`docs/rules.md`), the
same identifiers (`docs/identifiers.md`) and the same tables
(`docs/output_contract.md`).

How to set it up in GCP, run it and check it against the Python
pipeline: [`docs/dataform.md`](../docs/dataform.md).

## Layers

| Layer | Dataset | What is in it |
|---|---|---|
| Bronze | `hww_landed` | py-common's raw tables (`hww_signups`, `hww_survey`, `hww_was`, `hww_peer`) and `audit`. Declared in `definitions/sources/`, never written here. |
| Silver | `hww_silver` | Reference tables from `mappings/*.csv` (`ref_*`), the load each source reads (`raw_latest_loads`), one cleaned row per source row (`stg_*`), the stacked organisation rows (`int_org_rows`) and `data_quality_issues`. |
| Gold | `hww_gold` | The twelve tables of `docs/output_contract.md`, with the columns of `src/hww_dashboard/schema/`. Power BI reads these. |
| Checks | `hww_assertions` | Dataform assertions: the run's stops (`assert_*`), the output contract (`gold_*_contract`) and, when switched on, the comparison with expected tables (`acceptance_*`). |

## Files

```
workflow_settings.yaml      project, datasets and the settings config.toml holds
includes/hww.js             payload keys, [[was.sessions]], SQL for the cleaning rules
includes/reference_data.js  built from mappings/, the schemas and the identifier cases
scripts/build_reference_data.js
definitions/
  sources/       bronze declarations
  reference/     ref_* tables, organisation override chains
  staging/       raw_latest_loads, stg_*
  intermediate/  int_org_rows
  gold/          the reporting tables
  quality/       data_quality_issues
  assertions/    stops, output contract, acceptance
```

## Commands

From this folder, with Node.js 20 or later:

```bash
node scripts/build_reference_data.js
```

after changing anything in `mappings/`, `src/hww_dashboard/schema/` or
`tests/data/identifier_cases.json`; commit the rebuilt
`includes/reference_data.js` with it. CI fails while it is out of date.

```bash
npx @dataform/cli@3.0.71 compile
```

checks the models compile. Running them needs BigQuery credentials
(`npx @dataform/cli@3.0.71 init-creds`, then `run`); in GCP they run
from a Dataform repository, as `docs/dataform.md` describes.
