# Data quality report

Run at 2026-10-10 12:00.

## Inputs

- Account signups: 200 rows read (sheet 'Account signups').
- Survey export: 1 rows read, 93 columns.
- WAS database: 35 rows read.
- Peer mentoring: 11 rows read.

## Outputs

| table | rows |
|---|---|
| dim_employer | 168 |
| fact_signup | 185 |
| fact_engagement | 337 |
| dim_survey_response | 1 |
| fact_survey_answer | 36 |
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
| was_session_held | 70 |
| was_request | 35 |
| was_completed | 35 |
| peer_mentoring_interest | 11 |
| survey_completed | 1 |

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
- dim_employer: 168 employers, 35 found in more than one source.
- Employers not on Account signups (added from other files): ['Org 10']

## Attribute conflicts

41 employer(s) have rows that disagree. The chosen value is in dim_employer.

| employer_name | attribute_conflicts |
|---|---|
| Org 1 | sector: Private / Public; industry: Construction / Human Health & Social Work Activities; size_band: 1000+ / 50-249; sites_band: 1 / 6+ |
| Org 2 | sector: Other / Public; size_band: 10-49 / 1000+ / 50-249; sites_band: 1 / Not applicable (remote) |
| Org 3 | industry: Accommodation & Food Services / Public Administration, Defence, & Social Security; sites_band: 1 / 2-5 |
| Org 4 | sector: Private / Public; industry: Other / Property & Real Estate Services; size_band: 0-9 / 10-49 / 50-249 |
| Org 5 | sector: Charity or voluntary / Private; industry: Financial & Insurance / Human Health & Social Work Activities / Manufacturing; size_band: 1000+ / 250-999 / 50-249 |
| Org 6 | sector: Charity or voluntary / Private / Public; industry: Construction / Human Health & Social Work Activities; sites_band: 1 / 6+ |
| Org 7 | sector: Private / Public; industry: Human Health & Social Work Activities / Property & Real Estate Services; sites_band: 2-5 / 6+ |
| Org 8 | sector: Private / Public; industry: Education / Human Health & Social Work Activities; size_band: 1000+ / 250-999 / 50-249; sites_band: 1 / 6+ |
| Org 9 | sector: Charity or voluntary / Private; size_band: 0-9 / 10-49 |
| Org 11 | sector: Private / Public; industry: Accommodation & Food Services / Other; size_band: 10-49 / 1000+ / 250-999 / 50-249 |
| Org 12 | sector: Private / Public; industry: Financial & Insurance / Human Health & Social Work Activities; size_band: 0-9 / 10-49; sites_band: 1 / Not applicable (remote) |
| Org 13 | industry: Other / Transport & Storage (including postal); size_band: 1000+ / 250-999; sites_band: 1 / 6+ |
| Org 14 | industry: Education / Public Administration, Defence, & Social Security; size_band: 1000+ / 50-249; sites_band: 1 / 2-5 |
| Org 15 | industry: Education / Mining, Quarrying, & Utilities |
| Org 16 | industry: Human Health & Social Work Activities / Other; size_band: 1000+ / 250-999; sites_band: 2-5 / 6+ |
| Org 17 | industry: Human Health & Social Work Activities / Other; size_band: 250-999 / 50-249 |
| Org 18 | sector: Other / Public; industry: Education / Other; size_band: 10-49 / 1000+; sites_band: 1 / 2-5 |
| Org 19 | sector: Charity or voluntary / Private; size_band: 10-49 / 50-249 |
| Org 20 | industry: Education / Other |
| Org 21 | industry: Agriculture, Forestry, & Fishing / Human Health & Social Work Activities |
| Org 22 | sector: Other / Public; industry: Human Health & Social Work Activities / Manufacturing; size_band: 1000+ / 50-249; sites_band: 6+ / Not applicable (remote) |
| Org 23 | industry: Human Health & Social Work Activities / Property & Real Estate Services; size_band: 0-9 / 50-249 |
| Org 24 | sector: Private / Public; industry: Education / Human Health & Social Work Activities; size_band: 10-49 / 250-999 |
| Org 25 | sector: Other / Public; size_band: 0-9 / 50-249 |
| Org 26 | sector: Private / Public; industry: Human Health & Social Work Activities / Other; sites_band: 1 / 2-5 |
| Org 27 | industry: Education / Manufacturing; size_band: 1000+ / 50-249 |
| Org 28 | size_band: 10-49 / 1000+; sites_band: 1 / 6+ |
| Org 29 | sector: Other / Private / Public; industry: Business Administration & Support Services / Education / Human Health & Social Work Activities / Manufacturing / Other / Wholesale; sites_band: 1 / 2-5 / 6+ / Not applicable (remote) |
| Org 30 | sector: Charity or voluntary / Public; industry: Agriculture, Forestry, & Fishing / Human Health & Social Work Activities; size_band: 10-49 / 1000+ |
| Org 31 | sector: Private / Public; industry: Human Health & Social Work Activities / Manufacturing; sites_band: 1 / 6+ |
| Org 32 | sector: Charity or voluntary / Public; industry: Human Health & Social Work Activities / Property & Real Estate Services; size_band: 0-9 / 10-49 |
| Org 33 | industry: Human Health & Social Work Activities / Transport & Storage (including postal); sites_band: 1 / 2-5 |
| Org 34 | sector: Private / Public; industry: Information & Communication / Other; size_band: 10-49 / 50-249; sites_band: 1 / 6+ |
| Org 35 | sector: Private / Public; size_band: 10-49 / 250-999 |
| Org 52 | industry: Arts, Entertainment, Recreation, & Other Services / Other; size_band: 10-49 / 1000+; sites_band: 2-5 / 6+ |
| Org 80 | sector: Other / Public; industry: Education / Human Health & Social Work Activities / Other; size_band: 10-49 / 1000+; sites_band: 1 / 6+ |
| Org 81 | industry: Construction / Education / Human Health & Social Work Activities / Professional, Scientific, & Technical Activities / Public Administration, Defence, & Social Security; size_band: 10-49 / 1000+; sites_band: 2-5 / 6+ |
| Org 99 | industry: Business Administration & Support Services / Education / Human Health & Social Work Activities; size_band: 10-49 / 1000+ / 250-999; sites_band: 1 / 6+ |
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

- 93 columns in the export, 93 in mappings/survey_columns.csv.
- Columns never read (personal, technical or free text): What parts (if any) of the tool completion process could be improved?, Full Name, Created By (User Id), Date Updated, Source Url, Transaction Id, Payment Amount, Payment Date, Payment Status, Post Id, User Agent, User IP, Submission Speed (ms), PDF: HWW Employer Survey Tool, PDF: HWW Employer Survey Tool (Internal).
- 1 response(s) gave 36 answer row(s).
  - Q04: 1 respondent(s)
  - Q07: 1 respondent(s)
  - Q08: 1 respondent(s)
  - Q09: 1 respondent(s)
  - Q10: 1 respondent(s)
  - Q12: 1 respondent(s)

## Free-text flags

- 'Completed survey?': 106 row(s) filled in, 92 of them say 'Y' with no month.
- 'Requested WAS?': 13 row(s) filled in, 10 of them say 'Y' with no month.

## Warnings

- Account signups row 159: role was the org name 'Org 99', cleared.
- Account signups row 171: role was the org name 'Org 29', cleared.
- Survey export: 1 response(s) have a blank Company, so they cannot be linked to an employer (kept with a blank employer_id).
- WAS row 22: no Participant ID, using id 'row22'.
- WAS row 22: no Date of Enquiry, used Date allocated to adviser (2025-12-07).
- WAS: 35 session row(s) have details but no date (session 2: 35). Kept in fact_was_session, not counted as 'was_session_held'.
- WAS: 30 session(s) are dated before their enquiry date, e.g. WAS-5-S1 (2025-12-08 < 2025-12-16), WAS-6-S1 (2025-12-09 < 2026-01-06), WAS-7-S1 (2025-12-10 < 2026-01-08), WAS-8-S1 (2025-12-11 < 2026-01-08), WAS-9-S1 (2025-12-12 < 2026-01-26). Kept as-is.
- fact_engagement: 5 'was_session_held' event(s) are dated after today.

## Reconciliation

- survey: 104 employer(s) flagged 'Y' on Account signups, 0 with a survey response; 0 in both, 104 flagged with no record, 0 with a record but no flag.
- WAS: 13 employer(s) flagged 'Y' on Account signups, 35 with a WAS record; 5 in both, 8 flagged with no record, 30 with a record but no flag.

## Assumptions

- Sign-up date is the first day of the sign-up month (date_precision = month); the sheet only records the month.
- Survey completions come from the survey export and WAS requests from the WAS database. The 'Completed survey?' and 'Requested WAS?' columns on Account signups are kept in fact_signup and only used for the reconciliation section below.
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
