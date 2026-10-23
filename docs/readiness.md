# Production-readiness record

Last assessed on 2026-10-18, for the interim real-data runs and the
Dataform reference.

## RAP assessment

The NHS framework is cumulative: each level needs the ones below it.
Before the production-readiness work the project met most Silver
engineering practices, but could not claim Baseline overall without
recorded human review and open publication. The engineering
requirements for Silver are now largely met; a formal level still
depends on the process gates below. Gold needs CI that actually runs,
scheduled operation and demonstrated use, not just configuration.

| Criterion | Before | Now, and evidence |
|---|---|---|
| Open-source language | Met | Python; pyproject.toml |
| Version-controlled code | Met locally | Git history and logical commits; remote backup still needed |
| Reproduction instructions | Partial | README, constraints.txt, synthetic demo, runbook |
| Open publication | Not met | MIT licence supplied; owner to decide publication and review overrides first |
| Minimal manual intervention | Met locally | One command; cloud operation still to prove |
| Documentation | Mostly met | Runbook, schemas, rules, identifier and protection notes |
| Standard organisation | Met | src/, tests/, docs/ |
| Reusable functions | Met | Functional pipeline; separate operational modules |
| Coding standards | Met | Black, Ruff, strict mypy |
| Test framework | Met | Golden, unit, scenario, failure and reproducibility tests |
| Dependency information | Ranges only | constraints.txt and separate extras |
| Automatic logs | Console only | Per-run logs and structured cloud output |
| Tidy data | Met | Dimensions and long fact tables, schema contracts |
| Fully packaged | Met | Installable package and packaged schemas |
| Automatic CI | Config only | Windows/Linux and version jobs configured; not yet run on a remote |
| Schedule/event trigger | Missing | GCP procedure documented; deployment and alerts still to test |
| Signposted changes | Missing | CHANGELOG.md and version 0.2.0 |

The assessment used the
[NHS RAP levels](https://nhsdigital.github.io/rap-community-of-practice/introduction_to_RAP/levels_of_RAP/)
and the [Duck Book](https://best-practice-and-impact.github.io/qa-of-code-guidance/).
The Duck Book's fixed checklists have been withdrawn, so its
principles and chapters were used instead. Readable, modular code,
configuration, dependencies, data documentation, tests and
reproducibility all have code and documentation behind them.
Assurance still needs a person to validate the method, review changes
and check the outputs against their intended use.

## Remaining gates and limitations

- Run the optional live BigQuery test in a disposable dataset, then
  check failure rollback, job permissions, freshness and alerts in
  GCP. Tests against a fake client don't prove what BigQuery does.
  Build and test the deployment image.
- Complete the DPIA: retained organisation names and some free-form
  values can identify people, and pattern checks don't make data
  anonymous. Approve access, retention, region and any future limits
  on free-text values.
- Name the operators and their backup, the expected source arrival
  dates and who signs off reporting. Require human review and CI
  checks once there is a remote.
- Freeze uploads during a run, or use a fixed batch prefix: checksums
  don't pin object generations. Stop runs overlapping through
  orchestration.
- Folder rollback handles ordinary errors, but a killed process or a
  reader at the wrong moment can see the gap during the rename. The
  dashboard still reads CSV files and has no authentication; its
  owners need to add cloud reading and access control.
- Keep bare numeric date serials on the 1900 epoch, and agree a
  contract before accepting 1904 serials. Decide how to handle
  repeated survey Counts and display-formatted numeric identifiers
  with leading zeros before changing those rules.
- Ask for stable source identifiers for signup rows and survey
  responses (the survey tool's Entry Id on Survey info); ids derived
  from the row or from Count can move.
- Agree with the solution repository the raw heading translation and
  the privacy exclusions. Survey info, in the monitoring workbook, is
  the survey's source. Dataform must check the identifier cases,
  scenarios and golden results in BigQuery.
- Keep organisation overrides private, or outside the published
  repository, once real organisation names are added. Set CODEOWNERS
  and branch protection once there is a remote and named reviewers.

Until these are done the project can't claim to be ready for
production. It is ready for human review and cloud acceptance
testing.
