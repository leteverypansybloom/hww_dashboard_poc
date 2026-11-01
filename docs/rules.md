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

The Dataform column names the model in `dataform/` that implements
each rule (`docs/dataform.md`). Run the scenario files and the golden
files through the models to check them (`docs/output_contract.md`,
"Comparing another implementation"; `docs/dataform.md`, step 9).

The ASSUMPTIONS list printed at the end of every data quality report
says the same rules in a few lines, for readers of the report.

## Reading the inputs

| Id | Rule | Code | Tests | Dataform |
|---|---|---|---|---|
| R01 | Settings are checked before any file is read: every required setting with the right type, unique session numbers, a known completion rule, each source once in the priority list, a known output target. `${NAME}` takes an environment variable's value. | `load_config`, `check_config`, `interpolate` | TestCheckConfig, TestLoadConfig, TestInterpolate | `workflow_settings.yaml` vars, checked in `includes/hww.js` at compile time |
| R02 | A source is its exact `file`, or the newest file matching `file_pattern`: latest YYYY-MM-DD date in the name, then latest save time, then file name. | `input_file`, `newest_match`, `date_in_name` | TestNewestMatch, TestInputFile, TestDateInName | `raw_latest_loads` (the agreed file name only; `file_pattern` has no Dataform equivalent) |
| R03 | Headings come from the configured row. A blank heading takes its column letter; a repeated heading is numbered like pandas (`Other`, `Other.1`), skipping names already used. | `read_sheet`, `make_unique` | TestReadSheet, TestMakeUnique | py-common names the payload keys; `includes/hww.js` lists them |
| R04 | A missing file, sheet, heading row or column stops the run, naming it and suggesting close matches. | `read_sheet`, `require`, `suggest` | TestReadSheet, TestRequire, TestSuggest | `assert_loads_complete` |
| R05 | A column on the `[privacy]` list can't be configured as a business field, and a personal survey column must have the `drop` role. | `check_config`, `load_survey` | TestCheckConfig, TestLoadSurvey | py-common contracts: excluded columns are never loaded |
| R06 | A row whose every cell is blank is dropped. | `drop_blank_rows` | TestDropBlankRows | `hww.anyValue` in `stg_survey_responses`, `stg_was_requests`, `stg_peer` |
| R07 | A source with no usable rows stops the run, unless its section sets `allow_empty = true`. | `require_rows` | TestRun (test_ingest.py) | `assert_sources_not_empty` |
| R08 | Two WAS rows, or two peer rows, with the same id stop the run. | `require_unique_ids` | TestRequireUniqueIds, TestLoadWas, TestLoadPeer | `uniqueKey` on `stg_was_requests`, `stg_peer` |
| R09 | Mapping files may not have blank or conflicting rows, override cycles, or targets missing from `agreed_values.csv`. | `mapping_pairs`, `load_mappings`, `check_agreed_values` | TestMappingPairs, TestLoadMappings, TestCheckAgreedValues | `assert_mappings_valid` |

## Cleaning values

| Id | Rule | Code | Tests | Dataform |
|---|---|---|---|---|
| R10 | Every cell becomes tidy text: blanks empty, a whole decimal loses `.0`, `_x000D_` becomes a space, whitespace runs become one space, ends trimmed. | `clean_text` | TestCleanText; scenario | `hww.clean`, `hww.tidy` |
| R11 | Dates: an Excel date as it is; an Excel serial number on the 1900 calendar; ISO text year first; other text day first; anything else blank. | `to_date` | TestToDate | `hww.date` (ISO text only: the contracts type every date column) |
| R12 | Bands map through `mappings/*.csv`, ignoring case and spacing. A blank becomes Unknown; a value missing from the file becomes Unknown and is counted under Unmapped values. | `map_value`, `map_bands` | TestMapValue, TestMapBands; scenario | `ref_lookups`, `hww.band`; `data_quality_issues` |
| R13 | WAS topics and durations keep a value missing from the mapping as typed, and count it. | `map_value` | TestMapValue; scenario (Sleep hygiene) | `stg_was_sessions`, `stg_was_session_topics` |
| R14 | The agreed bands: size 0-9, 10-49, 50-249, 250-999, 1000+; sites 1, 2-5, 6+, Not applicable (remote). WAS `50-250` and `251-999` count as 50-249 and 250-999, and `5-8` as 6+. | `mappings/` | TestCheckAgreedValues; scenario | `ref_lookups`, `assert_mappings_valid` |

## Account signups

| Id | Rule | Code | Tests | Dataform |
|---|---|---|---|---|
| R20 | The month in column B is a merged cell, so it fills down; a non-blank month that isn't a date stops the run. | `load_signups` | TestLoadSignups; scenario | `stg_signups`, `assert_signup_months_valid` |
| R21 | A row with no organisation is dropped. Every other row is one user: duplicate organisations are kept here and merged only in `dim_employer`. | `load_signups` | TestLoadSignups, TestRun (test_wrangle.py); scenario | `stg_signups` |
| R22 | `signup_id` is SU and the Excel row number (at least 4 digits). A sign-up is dated the first of its month, with precision `month`. | `load_signups`, `build_engagement` | scenario | `stg_signups`, `fact_engagement` |
| R23 | A role that repeats the organisation's name is cleared. Roles are not output. | `load_signups` | TestLoadSignups | `stg_signups` (`role_was_org`) |
| R24 | "Completed survey?" and "Requested WAS?" read Y, Yes, N and No, with months in brackets. A month without a year gets the year closest to the sign-up month; an exact six-month tie goes to the later year. Blank means no. | `parse_flag`, `nearest_year` | TestParseFlag, TestNearestYear; scenario | `hww.flag`, `hww.flagDates` in `stg_signups` |
| R25 | The flags never create events. They are compared with the survey and WAS records in the report's Reconciliation section. | `reconcile` | TestReconcile | `data_quality_issues` (Reconciliation) |

## Survey

| Id | Rule | Code | Tests | Dataform |
|---|---|---|---|---|
| R30 | Survey responses are the rows of the `Survey info` sheet of the monitoring workbook (headings on row 2). `survey_columns.csv` says what each of its columns is; a column it doesn't list is ignored and reported, and a listed column missing from the sheet is reported. | `load_survey`, `validate_survey_columns` | TestValidateSurveyColumns, TestLoadSurvey | `stg_survey_responses`, `stg_survey_answers`, `data_quality_issues` |
| R31 | `response_id` is the cleaned `Count`. A response with no Count is dropped; of repeated Counts, the first in sheet order is kept. | `load_survey` | scenario (101, the row with no Count) | `stg_survey_responses` |
| R32 | Any value in a tick-box column means that option was chosen, named as in the catalogue, whatever the value says (a Welsh label counts too). A cell holding only whitespace, such as a space or a non-breaking space, is not a tick (R10). | `unpivot_survey` | TestUnpivotSurvey, TestLandedInputs (test_landing.py); scenario | `stg_survey_answers` |
| R33 | A single-choice answer is translated from Welsh for its question, then spelt as in the catalogue. An answer not in the catalogue is kept and reported. | `unpivot_survey`, `load_survey` | TestUnpivotSurvey; scenario (Weithiau, Maybe) | `stg_survey_answers`, `ref_survey_answer_translations` |
| R34 | Free text from the "Other (more info)" boxes is output only when `keep_other_free_text = true`. | `unpivot_survey` | TestUnpivotSurvey | `stg_survey_other_text`, `survey_other_text` |
| R35 | A response's bands are its own; one that is Unknown takes the employer's value. | `build_survey_tables` | TestBuildSurveyTables; scenario (102) | `dim_survey_response` |
| R36 | Figure 13: the percent for an answer is the respondents who chose it divided by the respondents who gave any answer to that question. | the dashboard's `survey_question_results` | TestSurveyQuestionResults (test_dashboard_data.py); scenario | A Power BI measure, not a table |
| R37 | The catalogue lists every option in `survey_answers.csv` order, then options seen only in the data (order 999). `answer_id` is the question id and the option's 2-digit position. | `build_question_catalogue` | TestBuildQuestionCatalogue; scenario (Q14-04) | `question_catalogue` |

## Workplace Advisor Support (WAS)

| Id | Rule | Code | Tests | Dataform |
|---|---|---|---|---|
| R40 | `was_request_id` is WAS- and the Participant ID, or WAS-row and the Excel row when the ID is blank. | `load_was` | TestLoadWas; scenario (WAS-row4) | `stg_was_requests` |
| R41 | A request with no enquiry date uses its allocation date. | `load_was` | scenario (WAS-2) | `stg_was_requests` |
| R42 | Each configured session with any detail becomes a row. Topics split on `;#`, are mapped, and keep their first occurrence. | `unpivot_was_sessions` | TestUnpivotWasSessions; scenario | `stg_was_sessions`, `stg_was_session_topics`, `fact_was_session` |
| R43 | A session counts as held only if it has a date. | `build_engagement` | scenario (WAS-2-S1) | `fact_engagement` |
| R44 | A request is completed by `completed_rule`: the session 1 summary date (`summary_1_sent`), the session 1 date (`session_1_held`), or the latest session date (`last_session_held`). | `build_engagement` | TestBuildEngagement; scenario (all three) | `fact_engagement` (`completed_rule`) |
| R45 | Sessions with no date, and sessions dated before their enquiry, are reported and kept as they are. | `check_was_sessions` | TestCheckWasSessions | `data_quality_issues` |

## Peer mentoring

| Id | Rule | Code | Tests | Dataform |
|---|---|---|---|---|
| R50 | `peer_id` is PM- and the Participant ID as typed (leading zeros kept), or PM-row and the Excel row. The file has no sites column, so sites are Unknown. | `load_peer` | TestLoadPeer; scenario | `stg_peer` |

## Employers

| Id | Rule | Code | Tests | Dataform |
|---|---|---|---|---|
| R60 | Names are compared by `name_key` (docs/identifiers.md). An override maps a name's key to a canonical name, following chains. | `name_key`, `org_name`, `load_mappings` | test_identifiers.py, TestOrgName, TestLoadMappings; scenario (Delta Trading, Beta Café) | `hww.nameKey`, `ref_org_overrides_resolved`, `assert_identifier_cases` |
| R61 | One employer per key. Its name is the most common spelling; on a tie, the one seen first. | `build_dim_employer` | TestBuildDimEmployer; scenario | `dim_employer` |
| R62 | Each attribute takes the most common known value; on a tie, a specific value over Other; then the value seen in the highest-priority source (`source_priority`: signups, survey, WAS, peer); then the value on the latest row, in the order signups, survey, WAS, peer. Unknown is ignored. | `pick_value`, `combine_org_rows` | TestPickValue, TestCombineOrgRows; scenario (Alpha, Beta, Gamma) | `int_org_rows`, `dim_employer` |
| R63 | `attribute_conflicts` lists each attribute's known values, sorted, where the rows disagree. | `build_dim_employer` | scenario | `dim_employer` |
| R64 | `employer_id` is E and the first 8 hex digits of the MD5 of the name's key. Two keys with one id stop the run. | `employer_id_for` | TestEmployerIdFor, test_identifiers.py | `hww.employerId`, `gold_dim_employer_contract` |
| R65 | Every row gets its organisation's `employer_id`; a row with no organisation gets none. | `attach_employer_ids` | TestAttachEmployerIds; scenario (103) | `employer_id` in each `stg_*` model |

## Engagement and calendar

| Id | Rule | Code | Tests | Dataform |
|---|---|---|---|---|
| R70 | One event per sign-up, survey response, WAS request, held session, completed request and peer expression of interest; `engagement_id` is the event type and the source row's id. | `build_engagement` | TestBuildEngagement; scenario | `fact_engagement` |
| R71 | An event with no date is kept (counted, not charted); events after the run date are reported. | `build_engagement` | TestBuildEngagement | `fact_engagement`, `data_quality_issues` |
| R72 | `dim_date` has every day of the whole financial years (1 April to 31 March) covering every date in the outputs; Q1 is April to June. | `build_dim_date`, `calendar_dates`, `fin_year` | TestBuildDimDate, TestCalendarDates, TestFinYear | `dim_date` |

## Outputs and checks

| Id | Rule | Code | Tests | Dataform |
|---|---|---|---|---|
| R80 | Only the columns in each table's schema are written, and every table is checked against its schema. | `csv_text`, `write_csv`, `output_schema` | test_output_schema.py | `gold_*_contract` |
| R81 | An email address, UK phone number, IPv4 address or web link in any output or the report stops the run, without repeating it. | `check_public_text` | TestCheckPublicText, TestWriteCsv, TestReport | `gold_*_contract` |
| R82 | The outputs are published all at once or not at all: a folder swap, or one BigQuery transaction. | `write_outputs`, `bigquery_output.publish` | TestWriteOutputs, test_bigquery_output.py | Gold tables wait for the `assert_*` stops; not one transaction (`docs/dataform.md`) |
| R83 | Every published set of outputs carries a run record with no cell values. | `run_record` | test_run_record.py | Dataform's workflow invocation history |
| R84 | A source with more than `max_row_drop` (10%) fewer rows than the last published run is a warning that needs attention. | `compare_with_previous` | TestCompareWithPrevious, TestRun (test_ingest.py) | `data_quality_issues` (Row counts), against the previous upload |
