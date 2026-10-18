# Test data

The tests read only this folder, the project's `mappings/` and files
they write to temporary folders. They never read the top-level
`config.toml` (which will point at the real data) or anything outside
the project, except where a test checks the shipped `config.toml`'s
own settings.

| Path | What it is |
|---|---|
| `config.toml` | Frozen copy of the project config. Reads `inputs/` and the live `mappings/`. Also the demo config: `python wrangle.py tests/data/config.toml` writes the synthetic tables to the project's `output/` (the tests write to temporary folders instead). |
| `inputs/*.xlsx` | Synthetic copies of the four dummy HWW workbooks. |

## How the inputs were made

Each workbook holds only the sheet the pipeline reads, copied cell for
cell from the dummy workbooks (organisations called Org 1, Org 2, ...
with made-up dates and answers): every value, its type, the row it is
on and the merged month cells on Account signups. Nothing else was
carried over: no other sheets, charts or document properties.

Values in personal and technical columns that the pipeline never reads
were replaced with reserved, obviously synthetic values. They keep the
shape of the real thing, so the privacy tests still have something to
catch:

| Workbook | Column | Synthetic value |
|---|---|---|
| Survey export | User IP | `192.0.2.10` (RFC 5737 documentation range) |
| Survey export | User Agent | `Mozilla/5.0 (synthetic test fixture)` |
| Survey export | Source Url and both PDF links | `https://example.org/...` (RFC 2606) |
| Survey export | Created By (User Id) | `1` |
| Survey export | The two free-text "Other" answers | Made-up text, still with Excel's `_x000D_` line breaks |
| WAS database | Preferred contact details | `contact@example.org` |
| Peer mentoring | Email Address | `name@example.org` |
| WAS database, peer mentoring | Path | `personal/name_example_org/Lists/...` |

The contact names (Jan Job, John Job) were already placeholders and
are unchanged.

Before the copies were committed, the code as it was before the package
refactor was run on them: every CSV matched `tests/golden/` byte for
byte, and the data quality report matched the one it wrote from the
dummy workbooks. So the snapshot describes these inputs exactly.

## Changing them

Change a workbook only for a deliberate test change, and then:

- keep every personal value synthetic (`example.org`, `192.0.2.x`);
- clear the author from the file's properties if your editor added it;
- refresh the snapshot with `python scripts/refresh_golden.py`, as
  described in `CONTRIBUTING.md` (Golden files).

`TestSyntheticInputs` in `tests/test_wrangle.py` fails if an email
address, IP address or link that is not one of the reserved ones
appears in an input.
