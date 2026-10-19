# Rule register

*The specification the Dataform models must meet. For whoever builds
them, and anyone checking a number.*

Each rule the pipeline applies has an id, a plain statement, the code
that implements it and the tests that check it. Three kinds of test
back the rules:

- **unit tests** (`tests/test_*.py`, classes named after the function);
- **hand-worked scenarios** (`tests/test_scenarios.py`): tiny workbooks
  whose expected tables were worked out from these rules by hand,
  never copied from the code's output (`tests/scenarios/README.md`);
- **the golden snapshot** (`tests/test_golden.py`): one realistic run,
  which catches any unintended change but checks the code against its
  own earlier output.

When a Dataform model implements a rule, add it to the Dataform column
and run the scenario files and the golden files through it
(`docs/output_contract.md`, "Comparing another implementation").

The ASSUMPTIONS list printed at the end of every data quality report
says the same rules in a few lines, for readers of the report.

## Reading the inputs

| Id | Rule | Code | Tests | Dataform |
|---|---|---|---|---|
| R01 | Settings are checked before any file is read: every required setting with the right type, unique session numbers, a known completion rule, each source once in the priority list, a known output target. `${NAME}` takes an environment variable's value. | `load_config`, `check_config`, `interpolate` | TestCheckConfig, TestLoadConfig, TestInterpolate | |
| R02 | A source is its exact `file`, or the newest file matching `file_pattern`: latest YYYY-MM-DD date in the name, then latest save time, then file name. | `input_file`, `newest_match`, `date_in_name` | TestNewestMatch, TestInputFile, TestDateInName | |
| R03 | Headings come from the configured row. A blank heading takes its column letter; a repeated heading is numbered like pandas (`Other`, `Other.1`), skipping names already used. | `read_sheet`, `make_unique` | TestReadSheet, TestMakeUnique | |
| R04 | A missing file, sheet, heading row or column stops the run, naming it and suggesting close matches. | `read_sheet`, `require`, `suggest` | TestReadSheet, TestRequire, TestSuggest | |
| R05 | A column on the `[privacy]` list can't be configured as a business field, and a personal survey column must have the `drop` role. | `check_config`, `load_survey` | TestCheckConfig, TestLoadSurvey | |
| R06 | A row whose every cell is blank is dropped. | `drop_blank_rows` | TestDropBlankRows | |
| R07 | A source with no usable rows stops the run, unless its section sets `allow_empty = true`. | `require_rows` | TestRun (test_ingest.py) | |
| R08 | Two WAS rows, or two peer rows, with the same id stop the run. | `require_unique_ids` | TestRequireUniqueIds, TestLoadWas, TestLoadPeer | |
| R09 | Mapping files may not have blank or conflicting rows, override cycles, or targets missing from `agreed_values.csv`. | `mapping_pairs`, `load_mappings`, `check_agreed_values` | TestMappingPairs, TestLoadMappings, TestCheckAgreedValues | |

## Cleaning values

| Id | Rule | Code | Tests | Dataform |
|---|---|---|---|---|
| R10 | Every cell becomes tidy text: blanks empty, a whole decimal loses `.0`, `_x000D_` becomes a space, whitespace runs become one space, ends trimmed. | `clean_text` | TestCleanText; scenario | |
| R11 | Dates: an Excel date as it is; an Excel serial number on the 1900 calendar; ISO text year first; other text day first; anything else blank. | `to_date` | TestToDate | |
| R12 | Bands map through `mappings/*.csv`, ignoring case and spacing. A blank becomes Unknown; a value missing from the file becomes Unknown and is counted under Unmapped values. | `map_value`, `map_bands` | TestMapValue, TestMapBands; scenario | |
| R13 | WAS topics and durations keep a value missing from the mapping as typed, and count it. | `map_value` | TestMapValue; scenario (Sleep hygiene) | |
| R14 | The agreed bands: size 0-9, 10-49, 50-249, 250-999, 1000+; sites 1, 2-5, 6+, Not applicable (remote). WAS `50-250` and `251-999` count as 50-249 and 250-999, and `5-8` as 6+. | `mappings/` | TestCheckAgreedValues; scenario | |

## Account signups

| Id | Rule | Code | Tests | Dataform |
|---|---|---|---|---|
| R20 | The month in column B is a merged cell, so it fills down; a non-blank month that isn't a date stops the run. | `load_signups` | TestLoadSignups; scenario | |
| R21 | A row with no organisation is dropped. Every other row is one user: duplicate organisations are kept here and merged only in `dim_employer`. | `load_signups` | TestLoadSignups, TestRun (test_wrangle.py); scenario | |
| R22 | `signup_id` is SU and the Excel row number (at least 4 digits). A sign-up is dated the first of its month, with precision `month`. | `load_signups`, `build_engagement` | scenario | |
| R23 | A role that repeats the organisation's name is cleared. Roles are not output. | `load_signups` | TestLoadSignups | |
| R24 | "Completed survey?" and "Requested WAS?" read Y, Yes, N and No, with months in brackets. A month without a year gets the year closest to the sign-up month; an exact six-month tie goes to the later year. Blank means no. | `parse_flag`, `nearest_year` | TestParseFlag, TestNearestYear; scenario | |
| R25 | The flags never create events. They are compared with the survey and WAS records in the report's Reconciliation section. | `reconcile` | TestReconcile | |

## Survey

| Id | Rule | Code | Tests | Dataform |
|---|---|---|---|---|
| R30 | `survey_columns.csv` says what each export column is; an export column it doesn't list is ignored and reported, and a listed column missing from the export is reported. | `load_survey`, `validate_survey_columns` | TestValidateSurveyColumns, TestLoadSurvey | |
| R31 | A response with no Entry Id is dropped; of repeated Entry Ids, the first is kept. | `load_survey` | scenario (101) | |
| R32 | Any value in a tick-box column means that option was chosen, named as in the catalogue. | `unpivot_survey` | TestUnpivotSurvey; scenario | |
| R33 | A single-choice answer is translated from Welsh for its question, then spelt as in the catalogue. An answer not in the catalogue is kept and reported. | `unpivot_survey`, `load_survey` | TestUnpivotSurvey; scenario (Weithiau, Maybe) | |
| R34 | Free text from "Other" boxes is output only when `keep_other_free_text = true`. | `unpivot_survey` | TestUnpivotSurvey, TestRun (test_ingest.py) | |
| R35 | A response's bands are its own; one that is Unknown takes the employer's value. | `build_survey_tables` | TestBuildSurveyTables; scenario (102) | |
| R36 | Figure 13: the percent for an answer is the respondents who chose it divided by the respondents who gave any answer to that question. | the dashboard's `survey_question_results` | TestSurveyQuestionResults (test_dashboard_data.py); scenario | |
| R37 | The catalogue lists every option in `survey_answers.csv` order, then options seen only in the data (order 999). `answer_id` is the question id and the option's 2-digit position. | `build_question_catalogue` | TestBuildQuestionCatalogue; scenario (Q14-04) | |

## Workplace Advisor Support (WAS)

| Id | Rule | Code | Tests | Dataform |
|---|---|---|---|---|
| R40 | `was_request_id` is WAS- and the Participant ID, or WAS-row and the Excel row when the ID is blank. | `load_was` | TestLoadWas; scenario (WAS-row4) | |
| R41 | A request with no enquiry date uses its allocation date. | `load_was` | scenario (WAS-2) | |
| R42 | Each configured session with any detail becomes a row. Topics split on `;#`, are mapped, and keep their first occurrence. | `unpivot_was_sessions` | TestUnpivotWasSessions; scenario | |
| R43 | A session counts as held only if it has a date. | `build_engagement` | scenario (WAS-2-S1) | |
| R44 | A request is completed by `completed_rule`: the session 1 summary date (`summary_1_sent`), the session 1 date (`session_1_held`), or the latest session date (`last_session_held`). | `build_engagement` | TestBuildEngagement; scenario (all three) | |
| R45 | Sessions with no date, and sessions dated before their enquiry, are reported and kept as they are. | `check_was_sessions` | TestCheckWasSessions | |

## Peer mentoring

| Id | Rule | Code | Tests | Dataform |
|---|---|---|---|---|
| R50 | `peer_id` is PM- and the Participant ID as typed (leading zeros kept), or PM-row and the Excel row. The file has no sites column, so sites are Unknown. | `load_peer` | TestLoadPeer; scenario | |

## Employers

| Id | Rule | Code | Tests | Dataform |
|---|---|---|---|---|
| R60 | Names are compared by `name_key` (docs/identifiers.md). An override maps a name's key to a canonical name, following chains. | `name_key`, `org_name`, `load_mappings` | test_identifiers.py, TestOrgName, TestLoadMappings; scenario (Delta Trading, Beta Café) | |
| R61 | One employer per key. Its name is the most common spelling; on a tie, the one seen first. | `build_dim_employer` | TestBuildDimEmployer; scenario | |
| R62 | Each attribute takes the most common known value; on a tie, a specific value over Other; then the value seen in the highest-priority source (`source_priority`: signups, survey, WAS, peer); then the value on the latest row, in the order signups, survey, WAS, peer. Unknown is ignored. | `pick_value`, `combine_org_rows` | TestPickValue, TestCombineOrgRows; scenario (Alpha, Beta, Gamma) | |
| R63 | `attribute_conflicts` lists each attribute's known values, sorted, where the rows disagree. | `build_dim_employer` | scenario | |
| R64 | `employer_id` is E and the first 8 hex digits of the MD5 of the name's key. Two keys with one id stop the run. | `employer_id_for` | TestEmployerIdFor, test_identifiers.py | |
| R65 | Every row gets its organisation's `employer_id`; a row with no organisation gets none. | `attach_employer_ids` | TestAttachEmployerIds; scenario (103) | |
| R66 | Employers whose names differ only by punctuation, spaces, `&` for "and", a leading "The" or a legal-form word at the end (Ltd, Limited, plc, LLP, CIC, Cyf, Cyfyngedig, CCC) are listed under Duplicates in the report as possibly one organisation. They are never merged automatically; an override merges them. Report only: no table changes, and not counted under Needs attention, because two organisations that really are different would be listed on every run. | `loose_key`, `possible_duplicates`, `report_duplicates` | TestLooseKey, TestPossibleDuplicates, TestReportDuplicates | not needed |

## Engagement and calendar

| Id | Rule | Code | Tests | Dataform |
|---|---|---|---|---|
| R70 | One event per sign-up, survey response, WAS request, held session, completed request and peer expression of interest; `engagement_id` is the event type and the source row's id. | `build_engagement` | TestBuildEngagement; scenario | |
| R71 | An event with no date is kept (counted, not charted); events after the run date are reported. | `build_engagement` | TestBuildEngagement | |
| R72 | `dim_date` has every day of the whole financial years (1 April to 31 March) covering every date in the outputs; Q1 is April to June. | `build_dim_date`, `calendar_dates`, `fin_year` | TestBuildDimDate, TestCalendarDates, TestFinYear | |

## Outputs and checks

| Id | Rule | Code | Tests | Dataform |
|---|---|---|---|---|
| R80 | Only the columns in each table's schema are written, and every table is checked against its schema. | `csv_text`, `write_csv`, `output_schema` | test_output_schema.py | |
| R81 | An email address, UK phone number, IPv4 address or web link in any output cell or report section stops the run. The message names the table and column (with how many cells) or the section, never the value. | `check_public_cells`, `check_public_text`, `Report.render` | TestCheckPublicCells, TestCheckPublicText, TestWriteCsv, TestReport | |
| R82 | The outputs are published all at once or not at all: a folder swap, or one BigQuery transaction. | `write_outputs`, `bigquery_output.publish` | TestWriteOutputs, test_bigquery_output.py | |
| R83 | Every published set of outputs carries a run record with no cell values. | `run_record` | test_run_record.py | |
| R84 | A source with more than `max_row_drop` (10%) fewer rows than the last published run is a warning that needs attention. | `compare_with_previous` | TestCompareWithPrevious, TestRun (test_ingest.py) | |
