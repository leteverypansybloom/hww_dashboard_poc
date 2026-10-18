# Identifiers

*For whoever builds the Dataform models, and anyone who stores ids from
the output tables.*

Every key in the output tables is made by a fixed rule from the input
values, so the same input always gives the same id. Dataform must make
the same ids, or reports moved from this pipeline's tables to
Dataform's would lose their relationships and saved filters. This page
gives each rule in plain words and in BigQuery SQL, and says how stable
each id is when a workbook is uploaded again.

py-common's raw tables keep each row's Excel row number in
`row_number` and the cell values in `payload` (`docs/RAW_TABLE_LAYOUT.md`
in py-common), so every rule below can be computed from them.

## Cleaning a value first

Before any rule, a cell becomes text by `clean_text`:

- empty, `None`, `NaN` and `NaT` become empty text;
- a whole number written as a decimal loses its `.0` (`12.0` becomes
  `12`);
- Excel's escaped carriage return `_x000D_` becomes a space;
- every run of whitespace becomes one space, and the ends are trimmed.
  Whitespace is what Python's `str.isspace()` counts: tab, line feed,
  vertical tab, form feed, carriage return, `\x1c` to `\x1f`, space,
  `\x85`, non-breaking space and the other Unicode spaces (` `,
  ` ` to ` `, ` `, ` `, ` `, ` `,
  `　`).

In SQL, with `v` the payload value as text:

```sql
TRIM(REGEXP_REPLACE(REPLACE(v, '_x000D_', ' '),
  r'[\s\x{0B}\x{1C}-\x{1F}\x{85}\x{A0}\x{1680}\x{2000}-\x{200A}\x{2028}\x{2029}\x{202F}\x{205F}\x{3000}]+',
  ' '))
```

## employer_id

`E` and the first 8 hex digits of the MD5 of the organisation's key.
The key (`name_key`) is the cleaned name with:

1. invisible formatting characters removed (Unicode category Cf: soft
   hyphens, zero-width spaces and joiners);
2. NFKC normalisation, which folds look-alikes such as full-width
   letters, ligatures and non-breaking spaces into plain ones, and joins
   a letter and its combining accent into one character;
3. case folding, then NFKC again (`ß` becomes `ss`; `Ŵ` becomes `ŵ`);
4. runs of whitespace collapsed to one space and the ends trimmed.

Expected SQL, with `name` the cleaned name:

```sql
CONCAT('E', SUBSTR(TO_HEX(MD5(
  TRIM(REGEXP_REPLACE(
    NORMALIZE_AND_CASEFOLD(REGEXP_REPLACE(name, r'\p{Cf}', ''), NFKC),
    r'[\s\x{85}\x{1C}-\x{1F}\x{2028}\x{2029}]+', ' '))
)), 1, 8))
```

BigQuery's `NORMALIZE_AND_CASEFOLD(..., NFKC)` is expected to match
steps 2 and 3. Confirm it with
[`tests/data/identifier_cases.json`](../tests/data/identifier_cases.json),
which lists awkward names (non-breaking and zero-width spaces,
full-width letters, `ß`, Welsh `ŵ`, a decomposed accent, a ligature,
numbers) with the key and id each must get. Every name in that file
must give the same id in Dataform.

Organisation overrides (`mappings/org_overrides.csv`) are matched by the
same key, and two rows whose raw names share a key must point at the
same canonical name. Rows from every source are grouped by key, so two
spellings are one employer when their keys match.

**Stability.** The id stays the same as long as the organisation's
name does. A renamed organisation gets a new id; an override from the
new name to the old one keeps the old id. The id is a hash of a name
that anyone can guess, so it is pseudonymous, not anonymous
(`docs/data_protection.md`).

**Collisions.** 8 hex digits give about four billion ids. Two different
keys sharing an id stops the run, asking for a longer id; at a few
thousand employers the chance is around 1 in 1,000. Lengthening the id
changes every id, so it is an output change.

## The other ids

| Id | Rule | Stable across uploads? |
|---|---|---|
| `signup_id` | `SU` and the Excel row number, zero-padded to at least four digits: `FORMAT('SU%04d', row_number)` | **No.** Inserting, deleting or sorting rows on Account signups renumbers every row below. Ask the data owners for an id column. |
| `response_id` | The survey tool's Entry Id, cleaned. | Yes. |
| `was_request_id` | `WAS-` and the cleaned Participant ID; `WAS-row` and the Excel row when the ID is blank. | Yes, while each request has a Participant ID. |
| `session_id` | `was_request_id`, `-S` and the session number from `[[was.sessions]]`. | As `was_request_id`. |
| `peer_id` | `PM-` and the cleaned Participant ID; `PM-row` and the Excel row when the ID is blank. | Yes, while each row has a Participant ID. |
| `engagement_id` | `event_type`, `-` and the source row's id (`signup_id`, Entry Id, `was_request_id`, `session_id` or `peer_id`). | As that id. |
| `answer_id` | `question_id`, `-` and the option's 2-digit position within its question, after sorting by `answer_order` (options seen only in the data come last, with order 999). | **No.** Adding an option to `survey_answers.csv` renumbers the options after it. Don't store `answer_id`s outside one run's tables. |

Participant IDs and Entry Ids are read as typed text, so `0011` keeps
its leading zeros. A number typed in Excel loses any display format
(`11` shown as `0011` is read as `11`).
