# Hand-worked scenarios

Three tiny workbooks, built by `workbooks.py`, in which each row is
chosen to exercise rules in [docs/rules.md](../../docs/rules.md). The
monitoring workbook holds two sheets, Account signups and Survey info
(headings on row 2, under a "Last updated" line). The
tables in `expected/` were worked out by hand from those rules, before
the pipeline was run on them; the only computed values are the
`employer_id`s, which are plain MD5s of keys worked out by hand. If a
scenario test fails, decide from the rules which side is wrong. Never
copy the pipeline's output into `expected/`.

`tests/test_scenarios.py` builds the workbooks, adds one organisation
override to a copy of the live mappings (`Delta Trading` becomes
`Gamma Group`), and runs the pipeline once for each WAS "completed"
rule.

## What each row is for

| Workbook row | Rules |
|---|---|
| Signups: Alpha Ltd, then ALPHA LTD on the next row with no month | R20 month fills down; R21 both are users; R61 one employer named Alpha Ltd |
| Signups: Alpha's flags `Y (Dec)` and `Y` | R24: December 2025 (nearest to the November sign-up), and yes with no date |
| Signups: Gamma Group `N` and `Y (Jan 26)` | R24: no, and January 2026 |
| Signups: the empty last row | R21 dropped |
| Survey 101, and a second 101 | R31 the first is kept; R33 Weithiau is Sometimes; R32 ticks, and the Headaches box holding a space is not ticked; Email address is never read (R05) |
| Survey 102 "beta café" with no bands | R60 matches Beta Café; R35 bands from the employer; R33 "Maybe" kept, catalogue Q14-04 (R37); R32 the Other box holding a non-breaking space is not ticked |
| Survey 103 with no Organisation | R65 no employer; its own bands, with industry `other_options` as Other (R12) |
| Survey row with no Count (Gamma Group) | R31 dropped, so it adds no response, event or employer attribute |
| WAS 1, Alpha Ltd | R42 three sessions, topics split and mapped; R44 each completion rule dates it differently |
| WAS 2, Delta Trading | R60 override to Gamma Group; R41 allocation date; R42/R43 a session with a duration but no date is kept, not held |
| WAS with no Participant ID | R40 `WAS-row4`; R13 the unmapped topic "Sleep hygiene" is kept |
| Peer 0007, "Beta Cafe" with a combining accent | R60 same key as Beta Café; R50 leading zeros kept |
| Alpha Ltd across all four sources | R62 sector by count (Private); size and sites tie on count and source, so the latest row (WAS) decides: 50-249 and 2-5; R63 conflicts listed |
| Beta Café: Charity or voluntary (signups) against Private (peer) | R62 a tie on count goes to the higher-priority source |
| Gamma Group: Other (signups) against Public (WAS) | R62 a specific value beats Other |

## Using them for Dataform

```
python tests/scenarios/workbooks.py scenario-inputs
```

writes the three workbooks to `scenario-inputs/`. Land them through
py-common into a test dataset with the override above, run the
Dataform models, and compare each table in `expected/` with Dataform's,
as in `docs/output_contract.md`. `fact_engagement.csv` is for
`completed_rule = "summary_1_sent"`; the two `was_completed_*.csv` files
hold the WAS completions under the other two rules.
