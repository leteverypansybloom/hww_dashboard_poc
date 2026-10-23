# Data quality report

Run at 2026-10-10 12:00.

## Needs attention

- 1 value(s) not in the mapping files: add each to the matching CSV in mappings/ (see Unmapped values).

## Inputs

- Account signups: 200 rows read (sheet 'Account signups') from dummy_HWW monitoring and reporting.xlsx (SHA-256 b87614310de1).
- Survey info: 103 rows read, 82 columns, from dummy_HWW monitoring and reporting.xlsx (SHA-256 b87614310de1).
- WAS database: 35 rows read from dummy_was_database.xlsx (SHA-256 378e0cf813b8).
- Peer mentoring: 11 rows read from dummy_peer_montoring.xlsx (SHA-256 f0e29dd68bb9).

## Outputs

| table | rows |
|---|---|
| dim_employer | 168 |
| fact_signup | 185 |
| fact_engagement | 439 |
| dim_survey_response | 103 |
| fact_survey_answer | 2867 |
| question_catalogue | 96 |
| fact_was_session | 105 |
| fact_was_session_topic | 105 |
| fact_event | 0 |
| badges | 0 |
| dim_date | 730 |

fact_engagement by event type:

| event_type | rows |
|---|---|
| account_signup | 185 |
| survey_completed | 103 |
| was_session_held | 70 |
| was_request | 35 |
| was_completed | 35 |
| peer_mentoring_interest | 11 |

## Rows dropped

- Account signups: 15 row(s) dropped - no organisation name (blank rows)

## Duplicates

- Account signups: 185 sign-up rows for 167 organisations.
- 9 organisation(s) appear more than once (each row kept as a user in fact_signup):
  - Org 29: 6 rows
  - Org 81: 5 rows
  - Org 80: 3 rows
  - Org 99: 3 rows
  - Org 11: 2 rows
  - Org 52: 2 rows
  - Org 120: 2 rows
  - Org 125: 2 rows
  - Org 164: 2 rows
- dim_employer: 168 employers, 99 found in more than one source.
- Employers not on Account signups (added from other files): ['Org 10']

## Attribute conflicts

101 employer(s) have rows that disagree. The chosen value is in dim_employer.

| employer_name | attribute_conflicts |
|---|---|
| Org 1 | sector: Other / Private / Public; industry: Construction / Human Health & Social Work Activities / Other; size_band: 1000+ / 50-249; sites_band: 1 / 2-5 / 6+ |
| Org 2 | sector: Other / Private / Public; industry: Education / Human Health & Social Work Activities; size_band: 10-49 / 1000+ / 50-249; sites_band: 1 / 2-5 / Not applicable (remote) |
| Org 3 | sector: Other / Private; industry: Accommodation & Food Services / Human Health & Social Work Activities / Public Administration, Defence, & Social Security; size_band: 250-999 / 50-249; sites_band: 1 / 2-5 |
| Org 4 | sector: Charity or voluntary / Private / Public; industry: Human Health & Social Work Activities / Other / Property & Real Estate Services; size_band: 0-9 / 10-49 / 50-249; sites_band: 1 / 2-5 |
| Org 5 | sector: Charity or voluntary / Private; industry: Education / Financial & Insurance / Human Health & Social Work Activities / Manufacturing; size_band: 10-49 / 1000+ / 250-999 / 50-249 |
| Org 6 | sector: Charity or voluntary / Private / Public; industry: Construction / Education / Human Health & Social Work Activities; size_band: 250-999 / 50-249; sites_band: 1 / 2-5 / 6+ |
| Org 7 | sector: Charity or voluntary / Private / Public; industry: Human Health & Social Work Activities / Property & Real Estate Services; size_band: 250-999 / 50-249; sites_band: 2-5 / 6+ |
| Org 8 | sector: Other / Private / Public; industry: Education / Human Health & Social Work Activities; size_band: 1000+ / 250-999 / 50-249; sites_band: 1 / 2-5 / 6+ |
| Org 9 | sector: Charity or voluntary / Private; industry: Education / Other; size_band: 0-9 / 10-49 / 250-999; sites_band: 1 / 2-5 |
| Org 11 | sector: Charity or voluntary / Private / Public; industry: Accommodation & Food Services / Other; size_band: 10-49 / 1000+ / 250-999 / 50-249 |
| Org 12 | sector: Charity or voluntary / Private / Public; industry: Financial & Insurance / Human Health & Social Work Activities / Public Administration, Defence, & Social Security; size_band: 0-9 / 10-49 / 50-249; sites_band: 1 / 2-5 / Not applicable (remote) |
| Org 13 | sector: Charity or voluntary / Public; industry: Other / Property & Real Estate Services / Transport & Storage (including postal); size_band: 10-49 / 1000+ / 250-999; sites_band: 1 / 2-5 / 6+ |
| Org 14 | sector: Charity or voluntary / Private; industry: Education / Other / Public Administration, Defence, & Social Security; size_band: 10-49 / 1000+ / 50-249; sites_band: 1 / 2-5 |
| Org 15 | sector: Private / Public; industry: Education / Mining, Quarrying, & Utilities / Public Administration, Defence, & Social Security; size_band: 10-49 / 50-249; sites_band: 2-5 / 6+ |
| Org 16 | industry: Human Health & Social Work Activities / Other / Public Administration, Defence, & Social Security; size_band: 1000+ / 250-999; sites_band: 2-5 / 6+ |
| Org 17 | sector: Other / Private; industry: Human Health & Social Work Activities / Other; size_band: 1000+ / 250-999 / 50-249; sites_band: 1 / 6+ |
| Org 18 | sector: Other / Public; industry: Education / Other; size_band: 10-49 / 1000+ / 250-999; sites_band: 1 / 2-5 |
| Org 19 | sector: Charity or voluntary / Private; industry: Other / Public Administration, Defence, & Social Security; size_band: 0-9 / 10-49 / 50-249; sites_band: 1 / 2-5 |
| Org 20 | sector: Charity or voluntary / Public; industry: Education / Other; size_band: 10-49 / 1000+ |
| Org 21 | sector: Other / Private; industry: Agriculture, Forestry, & Fishing / Human Health & Social Work Activities; size_band: 1000+ / 250-999; sites_band: 2-5 / 6+ |
| Org 22 | sector: Other / Public; industry: Human Health & Social Work Activities / Manufacturing; size_band: 1000+ / 250-999 / 50-249; sites_band: 2-5 / 6+ / Not applicable (remote) |
| Org 23 | industry: Human Health & Social Work Activities / Other / Property & Real Estate Services; size_band: 0-9 / 250-999 / 50-249; sites_band: 1 / 6+ |
| Org 24 | sector: Private / Public; industry: Education / Human Health & Social Work Activities / Other; size_band: 10-49 / 250-999; sites_band: 1 / 2-5 |
| Org 25 | sector: Charity or voluntary / Other / Public; industry: Other / Public Administration, Defence, & Social Security; size_band: 0-9 / 250-999 / 50-249; sites_band: 1 / 2-5 |
| Org 26 | sector: Other / Private / Public; industry: Human Health & Social Work Activities / Other / Property & Real Estate Services; sites_band: 1 / 2-5 |
| Org 27 | sector: Private / Public; industry: Education / Manufacturing; size_band: 10-49 / 1000+ / 50-249; sites_band: 1 / 2-5 |
| Org 28 | sector: Private / Public; industry: Public Administration, Defence, & Social Security / Wholesale; size_band: 10-49 / 1000+; sites_band: 1 / 2-5 / 6+ |
| Org 29 | sector: Other / Private / Public; industry: Business Administration & Support Services / Education / Human Health & Social Work Activities / Information & Communication / Manufacturing / Other / Wholesale; size_band: 10-49 / 1000+; sites_band: 1 / 2-5 / 6+ / Not applicable (remote) |
| Org 30 | sector: Charity or voluntary / Private / Public; industry: Agriculture, Forestry, & Fishing / Human Health & Social Work Activities / Manufacturing; size_band: 10-49 / 1000+ / 50-249 |
| Org 31 | sector: Private / Public; industry: Human Health & Social Work Activities / Manufacturing / Motor Trades; size_band: 10-49 / 50-249; sites_band: 1 / 6+ |
| Org 32 | sector: Charity or voluntary / Private / Public; industry: Human Health & Social Work Activities / Mining, Quarrying, & Utilities / Property & Real Estate Services; size_band: 0-9 / 10-49 / 250-999; sites_band: 1 / 2-5 |
| Org 33 | industry: Financial & Insurance / Human Health & Social Work Activities / Transport & Storage (including postal); size_band: 250-999 / 50-249; sites_band: 1 / 2-5 |
| Org 34 | sector: Private / Public; industry: Education / Information & Communication / Other; size_band: 10-49 / 250-999 / 50-249; sites_band: 1 / 2-5 / 6+ |
| Org 35 | sector: Private / Public; industry: Human Health & Social Work Activities / Other; size_band: 10-49 / 1000+ / 250-999; sites_band: 1 / 6+ |
| Org 36 | industry: Education / Other |
| Org 37 | sites_band: 2-5 / 6+ |
| Org 38 | sector: Private / Public; industry: Information & Communication / Manufacturing; size_band: 1000+ / 50-249 |
| Org 39 | sector: Charity or voluntary / Public; industry: Human Health & Social Work Activities / Other; size_band: 0-9 / 1000+; sites_band: 1 / 6+ |
| Org 40 | sector: Private / Public; industry: Human Health & Social Work Activities / Other; sites_band: 6+ / Not applicable (remote) |
| Org 41 | sector: Charity or voluntary / Public; industry: Human Health & Social Work Activities / Other; sites_band: 2-5 / Not applicable (remote) |
| Org 42 | sector: Private / Public; industry: Education / Other |
| Org 43 | sector: Charity or voluntary / Private; industry: Human Health & Social Work Activities / Mining, Quarrying, & Utilities; size_band: 10-49 / 1000+; sites_band: 2-5 / 6+ |
| Org 44 | industry: Mining, Quarrying, & Utilities / Other; size_band: 10-49 / 250-999 |
| Org 45 | sector: Private / Public; industry: Education / Other; size_band: 10-49 / 1000+; sites_band: 2-5 / 6+ |
| Org 46 | sector: Private / Public; industry: Other / Public Administration, Defence, & Social Security; sites_band: 1 / 6+ |
| Org 47 | industry: Accommodation & Food Services / Property & Real Estate Services; size_band: 0-9 / 50-249; sites_band: 1 / 2-5 |
| Org 48 | sector: Charity or voluntary / Private; industry: Education / Human Health & Social Work Activities; sites_band: 1 / 2-5 |
| Org 49 | industry: Human Health & Social Work Activities / Manufacturing; sites_band: 1 / 2-5 |
| Org 50 | sector: Other / Public; industry: Education / Other; sites_band: 2-5 / 6+ |
| Org 51 | industry: Human Health & Social Work Activities / Public Administration, Defence, & Social Security; size_band: 1000+ / 250-999 |
| Org 52 | sector: Charity or voluntary / Public; industry: Arts, Entertainment, Recreation, & Other Services / Other; size_band: 10-49 / 1000+ / 50-249; sites_band: 2-5 / 6+ |
| Org 53 | sector: Private / Public; industry: Construction / Education; size_band: 10-49 / 50-249; sites_band: 1 / 2-5 |
| Org 54 | sector: Charity or voluntary / Private; industry: Manufacturing / Retail; size_band: 10-49 / 250-999; sites_band: 1 / 2-5 |
| Org 55 | sector: Charity or voluntary / Private; size_band: 250-999 / 50-249; sites_band: 2-5 / 6+ |
| Org 56 | industry: Education / Public Administration, Defence, & Social Security; size_band: 10-49 / 1000+; sites_band: 1 / 6+ |
| Org 57 | sector: Private / Public; size_band: 0-9 / 10-49; sites_band: 1 / 2-5 |
| Org 58 | sector: Private / Public; industry: Accommodation & Food Services / Human Health & Social Work Activities; size_band: 0-9 / 10-49; sites_band: 1 / 6+ |
| Org 59 | industry: Human Health & Social Work Activities / Other; size_band: 1000+ / 50-249; sites_band: 1 / 6+ |
| Org 60 | industry: Human Health & Social Work Activities / Wholesale |
| Org 61 | sector: Charity or voluntary / Public; size_band: 1000+ / 250-999 |
| Org 62 | sector: Charity or voluntary / Private; industry: Education / Human Health & Social Work Activities; size_band: 250-999 / 50-249; sites_band: 2-5 / 6+ |
| Org 63 | sector: Charity or voluntary / Private; industry: Education / Other; size_band: 0-9 / 10-49 |
| Org 64 | sector: Charity or voluntary / Public; industry: Business Administration & Support Services / Human Health & Social Work Activities; size_band: 1000+ / 50-249 |
| Org 65 | industry: Education / Other |
| Org 66 | sector: Private / Public; industry: Human Health & Social Work Activities / Other; sites_band: 1 / 6+ |
| Org 67 | sector: Charity or voluntary / Private; industry: Education / Information & Communication; size_band: 0-9 / 1000+ |
| Org 68 | sector: Charity or voluntary / Public; industry: Education / Information & Communication; size_band: 250-999 / 50-249 |
| Org 69 | sector: Other / Private; industry: Education / Information & Communication; size_band: 250-999 / 50-249; sites_band: 1 / 6+ |
| Org 70 | sector: Private / Public; industry: Human Health & Social Work Activities / Wholesale; sites_band: 1 / 6+ |
| Org 71 | industry: Business Administration & Support Services / Human Health & Social Work Activities; size_band: 250-999 / 50-249; sites_band: 1 / 2-5 |
| Org 72 | sector: Private / Public; industry: Human Health & Social Work Activities / Information & Communication; sites_band: 2-5 / 6+ |
| Org 73 | industry: Education / Human Health & Social Work Activities; size_band: 10-49 / 50-249; sites_band: 1 / 6+ |
| Org 74 | sector: Charity or voluntary / Private; industry: Education / Human Health & Social Work Activities; size_band: 10-49 / 250-999; sites_band: 1 / 6+ |
| Org 75 | sector: Private / Public; industry: Human Health & Social Work Activities / Wholesale; size_band: 0-9 / 250-999; sites_band: 1 / 2-5 |
| Org 76 | sector: Private / Public; industry: Business Administration & Support Services / Human Health & Social Work Activities; size_band: 10-49 / 50-249 |
| Org 77 | sector: Charity or voluntary / Private; industry: Accommodation & Food Services / Human Health & Social Work Activities; size_band: 10-49 / 50-249; sites_band: 1 / 2-5 |
| Org 78 | sector: Private / Public; industry: Education / Other; sites_band: 1 / Not applicable (remote) |
| Org 79 | industry: Education / Other; size_band: 10-49 / 50-249; sites_band: 2-5 / 6+ |
| Org 80 | sector: Other / Private / Public; industry: Education / Financial & Insurance / Human Health & Social Work Activities / Mining, Quarrying, & Utilities / Other; size_band: 10-49 / 1000+ / 250-999; sites_band: 1 / 6+ |
| Org 81 | sector: Charity or voluntary / Private / Public; industry: Construction / Education / Human Health & Social Work Activities / Other / Professional, Scientific, & Technical Activities / Public Administration, Defence, & Social Security / Transport & Storage (including postal); size_band: 10-49 / 1000+ / 250-999 / 50-249; sites_band: 2-5 / 6+ |
| Org 82 | industry: Human Health & Social Work Activities / Other |
| Org 83 | sector: Private / Public; size_band: 1000+ / 50-249; sites_band: 1 / 2-5 |
| Org 84 | sector: Private / Public; industry: Human Health & Social Work Activities / Professional, Scientific, & Technical Activities; size_band: 1000+ / 50-249 |
| Org 85 | industry: Education / Manufacturing; size_band: 10-49 / 1000+; sites_band: 1 / 2-5 |
| Org 86 | sector: Charity or voluntary / Private; industry: Agriculture, Forestry, & Fishing / Human Health & Social Work Activities; size_band: 10-49 / 50-249 |
| Org 87 | sector: Private / Public; industry: Human Health & Social Work Activities / Property & Real Estate Services; size_band: 1000+ / 50-249; sites_band: 1 / 6+ |
| Org 88 | sector: Charity or voluntary / Public; industry: Human Health & Social Work Activities / Public Administration, Defence, & Social Security; size_band: 1000+ / 50-249; sites_band: 2-5 / 6+ |
| Org 89 | sector: Private / Public; industry: Education / Human Health & Social Work Activities; size_band: 0-9 / 10-49; sites_band: 1 / 2-5 |
| Org 90 | sector: Charity or voluntary / Private; industry: Human Health & Social Work Activities / Other; size_band: 10-49 / 250-999; sites_band: 1 / 6+ |
| Org 91 | industry: Education / Human Health & Social Work Activities |
| Org 92 | sector: Charity or voluntary / Other; size_band: 0-9 / 10-49; sites_band: 1 / 2-5 |
| Org 93 | sector: Charity or voluntary / Public; industry: Human Health & Social Work Activities / Property & Real Estate Services; size_band: 0-9 / 10-49 |
| Org 94 | sector: Other / Public; industry: Other / Public Administration, Defence, & Social Security; size_band: 10-49 / 250-999; sites_band: 1 / 6+ |
| Org 95 | sector: Other / Private; industry: Human Health & Social Work Activities / Other; size_band: 250-999 / 50-249 |
| Org 96 | sector: Private / Public; sites_band: 1 / Not applicable (remote) |
| Org 97 | size_band: 10-49 / 250-999; sites_band: 1 / 6+ |
| Org 98 | sector: Charity or voluntary / Private; industry: Human Health & Social Work Activities / Other; sites_band: 1 / Not applicable (remote) |
| Org 99 | sector: Private / Public; industry: Arts, Entertainment, Recreation, & Other Services / Business Administration & Support Services / Education / Human Health & Social Work Activities; size_band: 10-49 / 1000+ / 250-999; sites_band: 1 / 2-5 / 6+ |
| Org 120 | industry: Other / Public Administration, Defence, & Social Security; size_band: 10-49 / 50-249; sites_band: 1 / 6+ |
| Org 125 | sector: Private / Public; size_band: 10-49 / 250-999 |
| Org 10 | sector: Private / Public |

## Unmapped values

These were set to Unknown (bands) or kept as-is (topics, durations).
Add them to the matching CSV in mappings/ to fix.

| dimension | source | raw value | rows |
|---|---|---|---|
| size_band | signups | 1 10 | 1 |

## Survey checks

- 82 columns on Survey info, 82 in mappings/survey_columns.csv.
- Columns never read (personal, technical or free text): Month, Email address, What parts (if any) of the tool completion process could be improved?, CD.
- 103 response(s) gave 2867 answer row(s).
  - Q04: 103 respondent(s)
  - Q07: 103 respondent(s)
  - Q08: 103 respondent(s)
  - Q09: 103 respondent(s)
  - Q10: 103 respondent(s)
  - Q12: 102 respondent(s)

## Free-text flags

- 'Completed survey?': 106 row(s) filled in, 92 of them say 'Y' with no month.
- 'Requested WAS?': 13 row(s) filled in, 10 of them say 'Y' with no month.

## Warnings

- Account signups row 159: role was the org name 'Org 99', cleared.
- Account signups row 171: role was the org name 'Org 29', cleared.
- WAS row 22: no Participant ID, using id 'row22'.
- WAS row 22: no Date of Enquiry, used Date allocated to adviser (2025-12-07).
- WAS: 35 session row(s) have details but no date (session 2: 35). Kept in fact_was_session, not counted as 'was_session_held'.
- WAS: 30 session(s) are dated before their enquiry date, e.g. WAS-5-S1 (2025-12-08 < 2025-12-16), WAS-6-S1 (2025-12-09 < 2026-01-06), WAS-7-S1 (2025-12-10 < 2026-01-08), WAS-8-S1 (2025-12-11 < 2026-01-08), WAS-9-S1 (2025-12-12 < 2026-01-26). Kept as-is.
- fact_engagement: 5 'was_session_held' event(s) are dated after today.

## Reconciliation

- survey: 104 employer(s) flagged 'Y' on Account signups, 98 with a survey response; 61 in both, 43 flagged with no record, 37 with a record but no flag.
- WAS: 13 employer(s) flagged 'Y' on Account signups, 35 with a WAS record; 5 in both, 8 flagged with no record, 30 with a record but no flag.

## Assumptions

- Sign-up date is the first day of the sign-up month (date_precision = month); the sheet only records the month.
- Survey completions come from the Survey info tab of the monitoring workbook and WAS requests from the WAS database. The 'Completed survey?' and 'Requested WAS?' columns on Account signups are kept in fact_signup and only used for the reconciliation section below.
- A month written without a year (e.g. 'Y (Dec)') gets the year closest to the sign-up month (Dec next to a Jan 2026 sign-up = Dec 2025).
- 'Y' with no month gives flag = True and no date.
- 'other_options' is treated as the answer 'Other' (sector and industry).
- Size bands are reduced to 0-9 / 10-49 / 50-249 / 250-999 / 1000+ so every file fits. WAS '50-250' and '251-999' are treated as 50-249 and 250-999.
- Site bands are reduced to 1 / 2-5 / 6+ / Not applicable (remote). WAS '5-8' is treated as 6+ (overlaps 2-5 at exactly 5 sites).
- When rows for one organisation disagree, the most common value wins; on a tie a specific value beats 'Other', then source priority from config.toml, then the latest row.
- employer_id is a short hash of the lower-case organisation name, so it stays the same between runs.
- A WAS session only counts as 'was_session_held' if it has a date.
- Survey % for a question = respondents who ticked the answer / respondents who gave any answer to that question.
- Survey free text ('Other' boxes, 'What parts could be improved?') is not output unless keep_other_free_text = true in config.toml.
- Peer mentoring 'relationships' = expressions of interest (no matching dates recorded yet).
- Job roles, and the text typed into 'Completed survey?' and 'Requested WAS?', are not output; fact_signup keeps only the flags and dates read from that text.
