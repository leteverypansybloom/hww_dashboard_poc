# Production-readiness acceptance record

Prepared on 2026-10-18 for both interim real-data runs and the Dataform reference,
and updated on 2026-10-19. The approved work builds on `review/code-quality`. It
is now on `main`, which is pushed to the project's GitHub repository (not
publicly visible).

## RAP assessment

The NHS framework is cumulative: higher levels require the lower levels too.
Before this work the project met most Silver engineering practices but could
not claim Baseline overall without recorded human review and open publication.
After this work the engineering requirements for Silver are substantially met;
a formal level still depends on the process gates below. Gold requires actual
CI execution, scheduled operation and demonstrated use, not just configuration.

| Criterion | Before | After and evidence |
|---|---|---|
| Open-source language | Met | Python; pyproject.toml |
| Version-controlled code | Met locally | Git history and logical commits, pushed to the GitHub repository |
| Reproduction instructions | Partial | README, constraints.txt, synthetic demo, runbook |
| Open publication | Not met | MIT licence supplied; owner must decide publication and review overrides first |
| Minimal manual intervention | Met locally | One command; cloud operation still to prove |
| Documentation | Mostly met | Runbook, schemas, rules, identifier and protection notes |
| Standard organisation | Met | src/, tests/, docs/ |
| Reusable functions | Met | Functional pipeline; new operational modules |
| Coding standards | Met | Black, Ruff, strict mypy |
| Test framework | Met | Golden, unit, scenario, failure and reproducibility tests |
| Dependency information | Ranges only | constraints.txt and separate extras |
| Automatic logs | Console only | Per-run logs and structured cloud output |
| Tidy data | Met | Dimensions and long fact tables, schema contracts |
| Fully packaged | Met | Installable package and packaged schemas |
| Automatic CI | Config only | Windows/Linux and version jobs configured and pushed; confirm in the repository's Actions tab that they run and pass |
| Schedule/event trigger | Missing | GCP procedure documented; deployment and alerts still to test |
| Signposted changes | Missing | CHANGELOG.md and version 0.2.0 |

The [NHS levels](https://nhsdigital.github.io/rap-community-of-practice/introduction_to_RAP/levels_of_RAP/)
and [Duck Book](https://best-practice-and-impact.github.io/qa-of-code-guidance/)
are the review references. The Duck Book's fixed checklists were withdrawn when
reviewed; its principles and chapters were used instead. Readable/modular code,
configuration, dependencies, data documentation, tests and reproducibility now
have code and documentation evidence. Assurance still requires a human to
validate methodology, review changes and assess outputs against intended use.

## Remaining gates and limitations

- Run the optional live BigQuery test in a disposable dataset, then verify
  failure rollback, job permissions, freshness and alerts in GCP. Fake-client
  tests do not prove BigQuery service behavior. Build and test the deployment
  image; Docker Desktop was unavailable here.
- Complete the DPIA: retained organisation names and some free-form values can
  identify people. Pattern guards do not certify anonymity. Approve access,
  retention, region and any future free-text vocabulary restrictions.
- Name operators and backup, expected source arrivals and a reporting sign-off
  owner. Now that the remote exists, protect `main`: require a human review
  and passing CI checks before a merge.
- Freeze uploads for a run or use an immutable batch prefix. Checksums do not
  pin object generations. Prevent overlapping executions through orchestration.
- Folder rollback handles ordinary errors; process termination and concurrent
  readers can encounter a rename gap. The dashboard still reads CSV files and
  has no authentication; its owners must implement cloud reading and access.
- Keep bare numeric date serials on the 1900 epoch; agree a contract before
  accepting 1904 serials. Decide conflicting duplicate survey Entry IDs and
  leading-zero display-formatted numeric identifiers before changing those rules.
- Request a stable source identifier for signup rows; row-derived ids can move.
- Coordinate the survey source of truth/fixed landing name, raw heading
  translation and privacy exclusions with the solution repository. Dataform
  must validate identifier cases, scenarios and golden results in BigQuery.
- py-common docs still contain the original dummy survey with an IP address
  and report links in pushed history. Refer it to its owner/DPO for replacement
  and any history remediation; this implementation does not edit that repo.
- Keep organisation overrides private or move them outside the published repo
  when real organisation names are introduced. Set CODEOWNERS once the
  human reviewers are named.

These items prevent a claim of deployed production readiness today. The local
implementation is ready for human review and cloud acceptance testing.
