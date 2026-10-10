"""Healthy Working Wales dashboard: turn the raw spreadsheets into tidy CSV tables.

Run:
    python wrangle.py              (uses config.toml next to this file)
    python wrangle.py my.toml      (uses another config file)

Settings live in config.toml and the lookup tables in mappings/.
Every run writes the tables to the output folder plus data_quality_report.md.
"""

import hashlib
import re
import sys
import tomllib
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from openpyxl.utils import get_column_letter

HERE = Path(__file__).resolve().parent
UNKNOWN = "Unknown"
OTHER = "Other"
MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Column order of every output table. Empty tables are still written with these headers.
COLUMNS = {
    "dim_employer": [
        "employer_id", "employer_name", "sector", "industry", "size_band", "sites_band",
        "in_signups", "in_survey", "in_was", "in_peer", "attribute_conflicts",
    ],
    "fact_signup": [
        "signup_id", "employer_id", "signup_month", "role",
        "survey_flag", "survey_dates", "survey_raw", "was_flag", "was_dates", "was_raw",
    ],
    "fact_engagement": [
        "engagement_id", "employer_id", "date", "date_precision", "event_type", "source", "source_ref",
    ],
    "dim_survey_response": [
        "response_id", "employer_id", "date", "sector", "industry", "size_band", "sites_band",
    ],
    "fact_survey_answer": [
        "response_id", "employer_id", "date", "question_id", "question", "answer_id", "answer",
    ],
    "survey_other_text": ["response_id", "question_id", "other_text"],
    "question_catalogue": [
        "question_id", "question", "question_short", "question_type",
        "answer_id", "answer", "answer_short", "answer_order",
    ],
    "fact_was_session": [
        "session_id", "was_request_id", "employer_id", "session_number", "session_date",
        "duration", "summary_sent_date", "topics",
    ],
    "fact_was_session_topic": ["session_id", "topic"],
    "fact_event": [
        "event_id", "event_name", "event_type", "event_date", "employer_id", "action", "action_date",
    ],
    "badges": ["employer_id", "badge", "awarded_date"],
    "dim_date": ["date", "year", "month", "month_name", "month_start", "fin_year", "fin_quarter"],
}

ASSUMPTIONS = [
    "Sign-up date is the first day of the sign-up month (date_precision = month); the sheet only records the month.",
    "Survey completions come from the survey export and WAS requests from the WAS database. "
    "The 'Completed survey?' and 'Requested WAS?' columns on Account signups are kept in fact_signup "
    "and only used for the reconciliation section below.",
    "A month written without a year (e.g. 'Y (Dec)') gets the year closest to the sign-up month "
    "(Dec next to a Jan 2026 sign-up = Dec 2025).",
    "'Y' with no month gives flag = True and no date.",
    "'other_options' is treated as the answer 'Other' (sector and industry).",
    "Size bands are reduced to 0-9 / 10-49 / 50-249 / 250-999 / 1000+ so every file fits. "
    "WAS '50-250' and '251-999' are treated as 50-249 and 250-999.",
    "Site bands are reduced to 1 / 2-5 / 6+ / Not applicable (remote). WAS '5-8' is treated as 6+ "
    "(overlaps 2-5 at exactly 5 sites).",
    "When rows for one organisation disagree, the most common value wins; on a tie a specific value "
    "beats 'Other', then source priority from config.toml, then the latest row.",
    "employer_id is a short hash of the lower-case organisation name, so it stays the same between runs.",
    "A WAS session only counts as 'was_session_held' if it has a date.",
    "Survey % for a question = respondents who ticked the answer / respondents who gave any answer to that question.",
    "Survey free text ('Other' boxes, 'What parts could be improved?') is not output unless "
    "keep_other_free_text = true in config.toml.",
    "Peer mentoring 'relationships' = expressions of interest (no matching dates recorded yet).",
    "The job role on Account signups is kept in fact_signup (it can tell users apart within an employer).",
]


# ---------------------------------------------------------------- report


class Report:
    """Collects notes for data_quality_report.md, grouped by section."""

    ORDER = [
        "Inputs", "Outputs", "Rows dropped", "Duplicates", "Attribute conflicts",
        "Unmapped values", "Survey checks", "Free-text flags", "Warnings", "Reconciliation",
    ]

    def __init__(self):
        self.sections = {name: [] for name in self.ORDER}
        self.unmapped = Counter()  # (dimension, source, raw value) -> rows

    def add(self, section, line):
        self.sections[section].append(line)

    def dropped(self, source, count, reason):
        if count:
            self.add("Rows dropped", f"- {source}: {count} row(s) dropped - {reason}")

    def write(self, path):
        lines = [
            "# Data quality report",
            "",
            f"Run at {datetime.now():%Y-%m-%d %H:%M}.",
            "",
        ]
        if self.unmapped:
            table = pd.DataFrame(
                [(d, s, v, n) for (d, s, v), n in sorted(self.unmapped.items())],
                columns=["dimension", "source", "raw value", "rows"],
            )
            self.add("Unmapped values", "These were set to Unknown (bands) or kept as-is (topics, durations).")
            self.add("Unmapped values", "Add them to the matching CSV in mappings/ to fix.")
            self.add("Unmapped values", "")
            self.add("Unmapped values", markdown_table(table))
        for name in self.ORDER:
            lines.append(f"## {name}")
            lines.append("")
            lines.extend(self.sections[name] or ["None."])
            lines.append("")
        lines.append("## Assumptions")
        lines.append("")
        lines.extend(f"- {a}" for a in ASSUMPTIONS)
        lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")


def markdown_table(df):
    """Render a small DataFrame as a markdown table."""
    if df.empty:
        return "None."
    header = "| " + " | ".join(str(c) for c in df.columns) + " |"
    rule = "|" + "---|" * len(df.columns)
    body = ["| " + " | ".join(str(v).replace("|", "/") for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join([header, rule] + body)


# ---------------------------------------------------------------- cleaning helpers


def clean_text(value):
    """Turn any cell into tidy text.

    Blanks become '', 1 and '1' both become '1', and stray newlines,
    Excel '_x000D_' codes and double spaces are removed.
    """
    if value is None:
        return ""
    if isinstance(value, float):
        if pd.isna(value):
            return ""
        if value.is_integer():
            value = int(value)
    if value is pd.NaT:
        return ""
    text = str(value).replace("_x000D_", " ")
    return " ".join(text.split())


def to_date(value):
    """Return a date, or None if the cell is blank or not a date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = clean_text(value)
    if not text:
        return None
    parsed = pd.to_datetime(text, errors="coerce", dayfirst=True)
    return None if pd.isna(parsed) else parsed.date()


def make_unique(names):
    """Give repeated column names a suffix the same way pandas does: Other, Other.1, Other.2 ..."""
    seen = Counter()
    result = []
    for name in names:
        result.append(f"{name}.{seen[name]}" if seen[name] else name)
        seen[name] += 1
    return result


def read_sheet(path, sheet, header_row):
    """Read one Excel sheet as text-like objects with tidy, unique headers.

    Blank headers are named after their Excel column letter (e.g. 'B').
    An 'excel_row' column records where each row came from.
    """
    raw = pd.read_excel(path, sheet_name=sheet, header=None, dtype=object)
    headers = [clean_text(h) or get_column_letter(i + 1) for i, h in enumerate(raw.iloc[header_row - 1])]
    df = raw.iloc[header_row:].copy()
    df.columns = make_unique(headers)
    df["excel_row"] = range(header_row + 1, header_row + 1 + len(df))
    return df.reset_index(drop=True)


def require(df, columns, source):
    """Stop with a clear message if expected columns are missing."""
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise SystemExit(f"{source}: column(s) not found: {missing}. Check config.toml.")


def drop_blank_rows(df):
    """Remove rows where every cell (apart from excel_row) is blank."""
    cells = df.drop(columns="excel_row").map(clean_text)
    return df[(cells != "").any(axis=1)].copy()


def read_csv_text(path):
    """Read a mapping CSV with every value as text (Excel may save it with a BOM)."""
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")


def load_lookup(path):
    """Read a raw_value -> agreed_value CSV into a dict keyed by lower-case raw value."""
    table = read_csv_text(path)
    return {clean_text(r).casefold(): clean_text(a) for r, a in zip(table["raw_value"], table["agreed_value"])}


def map_value(raw, lookup, dimension, source, report, keep_unmapped=False):
    """Map a raw value to the agreed list.

    Blank -> Unknown. A value missing from the lookup is logged in the report
    and becomes Unknown, or is kept as-is when keep_unmapped is True.
    """
    text = clean_text(raw)
    if not text:
        return "" if keep_unmapped else UNKNOWN
    agreed = lookup.get(text.casefold())
    if agreed:
        return agreed
    report.unmapped[(dimension, source, text)] += 1
    return text if keep_unmapped else UNKNOWN


def org_name(raw, overrides):
    """Clean an organisation name and apply the manual override file."""
    name = clean_text(raw)
    return overrides.get(name.casefold(), name)


def employer_id_for(name):
    """Stable id from the lower-case name, e.g. 'E1a2b3c4d'."""
    return "E" + hashlib.md5(name.casefold().encode("utf-8")).hexdigest()[:8]


def iso(d):
    return d.isoformat() if d else ""


def fin_year(d):
    """UK financial year label, April to March, e.g. '2025-26'."""
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}-{str(start + 1)[2:]}"


# ---------------------------------------------------------------- free-text flags


def nearest_year(month, ref_month):
    """Year that puts this month closest to ref_month, e.g. 'Dec' near Jan 2026 -> 2025."""
    best_year, best_gap = None, None
    for year in (ref_month.year - 1, ref_month.year, ref_month.year + 1):
        gap = abs((year - ref_month.year) * 12 + month - ref_month.month)
        # '<=' so that an exact 6-month tie goes to the later year.
        if best_gap is None or gap <= best_gap:
            best_year, best_gap = year, gap
    return best_year


def parse_flag(raw, ref_month):
    """Read text like 'Y', 'Y (Dec)' or 'Y (Nov 25 & Aug 26)'.

    Returns (flag, dates, problem):
      flag    True / False, or None if the text could not be read
      dates   list of first-of-month dates found in the brackets
      problem '' or a note for the report
    A month without a year gets the year that puts it closest to ref_month.
    """
    text = clean_text(raw)
    if not text:
        return False, [], ""
    first_word = text.split("(")[0].strip().casefold()
    if first_word in ("n", "no"):
        return False, [], ""
    if first_word not in ("y", "yes"):
        return None, [], f"could not read '{text}'"

    dates = []
    problem = ""
    inside = re.search(r"\((.*)\)", text)
    if inside:
        for part in re.split(r"&|,| and ", inside.group(1)):
            part = part.strip()
            if not part:
                continue
            match = re.match(r"([A-Za-z]+)\.?\s*(\d{2}|\d{4})?$", part)
            month = MONTHS.get(match.group(1)[:3].casefold()) if match else None
            if month is None:
                problem = f"could not read date '{part}' in '{text}'"
                continue
            if match.group(2):
                year = int(match.group(2))
                if year < 100:
                    year += 2000
            elif ref_month:
                year = nearest_year(month, ref_month)
            else:
                problem = f"no year and no sign-up month for '{text}'"
                continue
            dates.append(date(year, month, 1))
    return True, dates, problem


# ---------------------------------------------------------------- sources


def load_signups(cfg, folder, lookups, overrides, report):
    """Account signups tab: one row per user sign-up."""
    df = read_sheet(folder / cfg["file"], cfg["sheet"], cfg["header_row"])
    keys = ["month", "org", "role", "size", "sector", "industry", "sites", "completed_survey", "requested_was"]
    require(df, [cfg[k] for k in keys], "Account signups")
    report.add("Inputs", f"- Account signups: {len(df)} rows read (sheet '{cfg['sheet']}').")

    # The month is a merged cell, so only the first row of each month has it.
    df["month"] = df[cfg["month"]].map(to_date).ffill()

    df["org"] = df[cfg["org"]].map(lambda v: org_name(v, overrides))
    blank = df["org"] == ""
    report.dropped("Account signups", int(blank.sum()), "no organisation name (blank rows)")
    df = df[~blank].copy()

    no_month = df["month"].isna()
    if no_month.any():
        report.add("Warnings", f"- Account signups: {int(no_month.sum())} row(s) have no month.")

    # Sometimes the organisation name was typed into the role column.
    df["role"] = df[cfg["role"]].map(clean_text)
    role_is_org = df["role"].str.casefold() == df["org"].str.casefold()
    for row in df[role_is_org].itertuples():
        report.add("Warnings", f"- Account signups row {row.excel_row}: role was the org name '{row.role}', cleared.")
    df.loc[role_is_org, "role"] = ""

    df["sector"] = [map_value(v, lookups["sector"], "sector", "signups", report) for v in df[cfg["sector"]]]
    df["industry"] = [map_value(v, lookups["industry"], "industry", "signups", report) for v in df[cfg["industry"]]]
    df["size_band"] = [map_value(v, lookups["size_band"], "size_band", "signups", report) for v in df[cfg["size"]]]
    df["sites_band"] = [map_value(v, lookups["sites_band"], "sites_band", "signups", report) for v in df[cfg["sites"]]]

    df["signup_id"] = df["excel_row"].map(lambda r: f"SU{r:04d}")
    df["signup_month"] = df["month"]

    # Turn the 'Y (Dec)' style text into a flag and dates, keeping the raw text.
    for column, prefix in ((cfg["completed_survey"], "survey"), (cfg["requested_was"], "was")):
        flags, dates, raws = [], [], []
        for value, month, excel_row in zip(df[column], df["month"], df["excel_row"]):
            flag, found, problem = parse_flag(value, month)
            if problem:
                report.add("Free-text flags", f"- Account signups row {excel_row}, '{column}': {problem}")
            for d in found:
                if d > date.today():
                    report.add("Free-text flags", f"- Account signups row {excel_row}, '{column}': '{clean_text(value)}' read as {d}, which is in the future.")
            flags.append(flag)
            dates.append(";".join(d.isoformat() for d in found))
            raws.append(clean_text(value))
        df[f"{prefix}_flag"] = flags
        df[f"{prefix}_dates"] = dates
        df[f"{prefix}_raw"] = raws
        with_text = sum(1 for r in raws if r)
        no_date = sum(1 for f, d in zip(flags, dates) if f and not d)
        report.add(
            "Free-text flags",
            f"- '{column}': {with_text} row(s) filled in, {no_date} of them say 'Y' with no month.",
        )
    return df


def unpivot_survey(df, columns_map, answer_lookup, translations, keep_other_text):
    """Turn the wide survey export into long rows.

    columns_map: survey_columns.csv as a DataFrame (column, role, question_id, option_or_note).
    answer_lookup: (question_id, lower-case answer) -> answer as written in survey_answers.csv.
    translations: (question_id, lower-case raw answer) -> English answer.
    Returns (answers, other_text, new_answers):
      answers      one row per ticked option or single answer: response_id, question_id, answer
      other_text   free text typed into 'Other' boxes (empty unless keep_other_text)
      new_answers  (question_id, answer) pairs not found in survey_answers.csv
    """
    answers, other_text, new_answers = [], [], Counter()
    question_columns = columns_map[columns_map["role"].isin(["single", "tick", "other_text"])]
    question_columns = question_columns[question_columns["column"].isin(df.columns)]
    for _, row in df.iterrows():
        response_id = row["response_id"]
        for spec in question_columns.itertuples():
            text = clean_text(row[spec.column])
            if not text:
                continue
            qid = spec.question_id
            if spec.role == "tick":
                # Any value in a tick-box column means the box was ticked; the option comes from the mapping.
                answer = spec.option_or_note
            elif spec.role == "single":
                answer = translations.get((qid, text.casefold()), text)
                answer = answer_lookup.get((qid, answer.casefold()), answer)
            else:
                if keep_other_text:
                    other_text.append({"response_id": response_id, "question_id": qid, "other_text": text})
                continue
            if (qid, answer.casefold()) not in answer_lookup:
                new_answers[(qid, answer)] += 1
            answers.append({"response_id": response_id, "question_id": qid, "answer": answer})
    answers = pd.DataFrame(answers, columns=["response_id", "question_id", "answer"]).drop_duplicates()
    other_text = pd.DataFrame(other_text, columns=COLUMNS["survey_other_text"])
    return answers, other_text, new_answers


def load_survey(cfg, folder, maps, lookups, overrides, report):
    """Employer survey export: one row per response, one column per question or tick box."""
    df = read_sheet(folder / cfg["file"], cfg["sheet"], cfg["header_row"])
    report.add("Inputs", f"- Survey export: {len(df)} rows read, {len(df.columns) - 1} columns.")

    columns_map = read_csv_text(maps / "survey_columns.csv")
    known = set(columns_map["column"])
    in_file = [c for c in df.columns if c != "excel_row"]
    unexpected = [c for c in in_file if c not in known]
    missing = [c for c in columns_map["column"] if c not in in_file]
    report.add("Survey checks", f"- {len(in_file)} columns in the export, {len(known)} in mappings/survey_columns.csv.")
    if unexpected:
        report.add("Survey checks", f"- **New columns not in survey_columns.csv (ignored):** {unexpected}")
    if missing:
        report.add("Survey checks", f"- **Columns in survey_columns.csv but not in the export:** {missing}")
    dropped = list(columns_map.loc[columns_map["role"] == "drop", "column"])
    report.add("Survey checks", f"- Columns never read (personal, technical or free text): {', '.join(dropped)}.")

    def column_for(role):
        found = columns_map.loc[columns_map["role"] == role, "column"]
        if found.empty or found.iloc[0] not in df.columns:
            raise SystemExit(f"Survey: no column with role '{role}' found. Check mappings/survey_columns.csv.")
        return found.iloc[0]

    df = drop_blank_rows(df)
    df["response_id"] = df[column_for("response_id")].map(clean_text)
    no_id = df["response_id"] == ""
    report.dropped("Survey export", int(no_id.sum()), "no Entry Id")
    df = df[~no_id]
    repeated = df["response_id"].duplicated()
    report.dropped("Survey export", int(repeated.sum()), "repeated Entry Id")
    df = df[~repeated].copy()

    df["date"] = df[column_for("date")].map(to_date)
    df["org"] = df[column_for("org")].map(lambda v: org_name(v, overrides))
    df["sector"] = [map_value(v, lookups["sector"], "sector", "survey", report) for v in df[column_for("sector")]]
    df["industry"] = [
        map_value(v, lookups["industry"], "industry", "survey", report) for v in df[column_for("industry")]
    ]
    df["size_band"] = [
        map_value(v, lookups["size_band"], "size_band", "survey", report) for v in df[column_for("size")]
    ]
    df["sites_band"] = [
        map_value(v, lookups["sites_band"], "sites_band", "survey", report) for v in df[column_for("sites")]
    ]
    no_org = int((df["org"] == "").sum())
    if no_org:
        report.add(
            "Warnings",
            f"- Survey export: {no_org} response(s) have a blank Company, so they cannot be linked to an employer "
            "(kept with a blank employer_id).",
        )

    catalogue = read_csv_text(maps / "survey_answers.csv")
    answer_lookup = {(q, a.casefold()): a for q, a in zip(catalogue["question_id"], catalogue["answer"])}
    trans = read_csv_text(maps / "survey_answer_translations.csv")
    translations = {(q, clean_text(r).casefold()): a for q, r, a in zip(trans["question_id"], trans["raw_answer"], trans["answer"])}

    answers, other_text, new_answers = unpivot_survey(
        df, columns_map, answer_lookup, translations, cfg["keep_other_free_text"]
    )
    for (qid, answer), n in sorted(new_answers.items()):
        report.add(
            "Survey checks",
            f"- Answer not in survey_answers.csv (kept, add it or a translation): {qid} '{answer}' x{n}",
        )
    return df, answers, other_text, columns_map


def load_was(cfg, folder, lookups, overrides, report):
    """WAS database: one row per support request, with up to three sessions."""
    df = read_sheet(folder / cfg["file"], cfg["sheet"], cfg["header_row"])
    keys = ["id", "org", "enquiry_date", "fallback_enquiry_date", "size", "sector", "industry", "sites"]
    session_columns = [s[k] for s in cfg["sessions"] for k in ("date", "duration", "summary_sent", "topics") if k in s]
    require(df, [cfg[k] for k in keys] + session_columns, "WAS")
    report.add("Inputs", f"- WAS database: {len(df)} rows read.")

    df = drop_blank_rows(df)
    df["org"] = df[cfg["org"]].map(lambda v: org_name(v, overrides))
    blank = df["org"] == ""
    report.dropped("WAS database", int(blank.sum()), "no organisation name")
    df = df[~blank].copy()

    ids = []
    for value, excel_row in zip(df[cfg["id"]], df["excel_row"]):
        text = clean_text(value)
        if not text:
            text = f"row{excel_row}"
            report.add("Warnings", f"- WAS row {excel_row}: no {cfg['id']}, using id '{text}'.")
        ids.append(f"WAS-{text}")
    df["was_request_id"] = ids

    dates = []
    for value, fallback, excel_row in zip(df[cfg["enquiry_date"]], df[cfg["fallback_enquiry_date"]], df["excel_row"]):
        enquiry = to_date(value)
        if enquiry is None:
            enquiry = to_date(fallback)
            report.add(
                "Warnings",
                f"- WAS row {excel_row}: no {cfg['enquiry_date']}, used {cfg['fallback_enquiry_date']} ({iso(enquiry) or 'blank'}).",
            )
        dates.append(enquiry)
    df["enquiry_date"] = dates

    df["sector"] = [map_value(v, lookups["sector"], "sector", "was", report) for v in df[cfg["sector"]]]
    df["industry"] = [map_value(v, lookups["industry"], "industry", "was", report) for v in df[cfg["industry"]]]
    df["size_band"] = [map_value(v, lookups["size_band"], "size_band", "was", report) for v in df[cfg["size"]]]
    df["sites_band"] = [map_value(v, lookups["sites_band"], "sites_band", "was", report) for v in df[cfg["sites"]]]

    # Unpivot sessions 1-3 into one row per session.
    sessions, topics = [], []
    for _, row in df.iterrows():
        for s in cfg["sessions"]:
            session_date = to_date(row[s["date"]])
            duration = map_value(row[s["duration"]], lookups["was_duration"], "was_duration", "was", report, True) if "duration" in s else ""
            summary = to_date(row[s["summary_sent"]]) if "summary_sent" in s else None
            raw_topics = clean_text(row[s["topics"]]) if "topics" in s else ""
            if not (session_date or duration or summary or raw_topics):
                continue
            session_id = f"{row['was_request_id']}-S{s['number']}"
            topic_list = []
            for part in raw_topics.split(cfg["topic_separator"]):
                if clean_text(part):
                    topic = map_value(part, lookups["was_topic"], "was_topic", "was", report, True)
                    if topic not in topic_list:
                        topic_list.append(topic)
            for topic in topic_list:
                topics.append({"session_id": session_id, "topic": topic})
            sessions.append({
                "session_id": session_id,
                "was_request_id": row["was_request_id"],
                "org": row["org"],
                "session_number": s["number"],
                "session_date": session_date,
                "duration": duration,
                "summary_sent_date": summary,
                "topics": "; ".join(topic_list),
            })
    sessions = pd.DataFrame(sessions)
    topics = pd.DataFrame(topics, columns=COLUMNS["fact_was_session_topic"])

    undated = sessions[sessions["session_date"].isna()] if not sessions.empty else sessions
    if len(undated):
        counts = undated["session_number"].value_counts().sort_index()
        detail = ", ".join(f"session {n}: {c}" for n, c in counts.items())
        report.add(
            "Warnings",
            f"- WAS: {len(undated)} session row(s) have details but no date ({detail}). "
            "Kept in fact_was_session, not counted as 'was_session_held'.",
        )
    if not sessions.empty:
        merged = sessions.merge(df[["was_request_id", "enquiry_date"]], on="was_request_id")
        early = merged[merged["session_date"].notna() & merged["enquiry_date"].notna()
                       & (merged["session_date"] < merged["enquiry_date"])]
        if len(early):
            examples = ", ".join(
                f"{r.session_id} ({r.session_date} < {r.enquiry_date})" for r in early.head(5).itertuples()
            )
            report.add(
                "Warnings",
                f"- WAS: {len(early)} session(s) are dated before their enquiry date, e.g. {examples}. Kept as-is.",
            )
    return df, sessions, topics


def load_peer(cfg, folder, lookups, overrides, report):
    """Peer mentoring list: one row per expression of interest."""
    df = read_sheet(folder / cfg["file"], cfg["sheet"], cfg["header_row"])
    require(df, [cfg[k] for k in ("id", "org", "interest_date", "size", "sector", "industry")], "Peer mentoring")
    report.add("Inputs", f"- Peer mentoring: {len(df)} rows read.")

    df = drop_blank_rows(df)
    df["org"] = df[cfg["org"]].map(lambda v: org_name(v, overrides))
    blank = df["org"] == ""
    report.dropped("Peer mentoring", int(blank.sum()), "no organisation name")
    df = df[~blank].copy()

    df["peer_id"] = [f"PM-{clean_text(v) or 'row' + str(r)}" for v, r in zip(df[cfg["id"]], df["excel_row"])]
    df["interest_date"] = df[cfg["interest_date"]].map(to_date)
    df["sector"] = [map_value(v, lookups["sector"], "sector", "peer", report) for v in df[cfg["sector"]]]
    df["industry"] = [map_value(v, lookups["industry"], "industry", "peer", report) for v in df[cfg["industry"]]]
    df["size_band"] = [map_value(v, lookups["size_band"], "size_band", "peer", report) for v in df[cfg["size"]]]
    df["sites_band"] = UNKNOWN  # not collected in this file
    return df


# ---------------------------------------------------------------- employers


def pick_value(values, sources, positions, priority):
    """Choose one value for an employer from all its rows.

    Most common known value wins. Ties: a specific value beats 'Other',
    then the higher-priority source, then the latest row.
    Returns (chosen value, list of all distinct known values).
    """
    candidates = {}
    for value, source, position in zip(values, sources, positions):
        if value == UNKNOWN:
            continue
        c = candidates.setdefault(value, {"count": 0, "source_rank": len(priority), "latest": -1})
        c["count"] += 1
        c["source_rank"] = min(c["source_rank"], priority.index(source))
        c["latest"] = max(c["latest"], position)
    if not candidates:
        return UNKNOWN, []
    ranked = sorted(
        candidates.items(),
        key=lambda item: (-item[1]["count"], item[0] == OTHER, item[1]["source_rank"], -item[1]["latest"]),
    )
    return ranked[0][0], sorted(candidates)


def build_dim_employer(org_rows, priority, report):
    """One row per organisation from every source, with a single value per attribute."""
    org_rows = org_rows[org_rows["org"] != ""].copy()
    org_rows["key"] = org_rows["org"].str.casefold()
    rows = []
    for key, group in org_rows.groupby("key", sort=False):
        name = Counter(group["org"]).most_common(1)[0][0]
        spellings = sorted(set(group["org"]))
        if len(spellings) > 1:
            report.add("Duplicates", f"- Spellings merged into '{name}': {spellings}")
        row = {"employer_id": employer_id_for(name), "employer_name": name}
        conflicts = []
        for attribute in ("sector", "industry", "size_band", "sites_band"):
            value, distinct = pick_value(group[attribute], group["source"], group["position"], priority)
            row[attribute] = value
            if len(distinct) > 1:
                conflicts.append(f"{attribute}: {' | '.join(distinct)}")
        row["attribute_conflicts"] = "; ".join(conflicts)
        for source in ("signups", "survey", "was", "peer"):
            row[f"in_{source}"] = bool((group["source"] == source).any())
        rows.append(row)
    dim = pd.DataFrame(rows, columns=COLUMNS["dim_employer"])

    if dim["employer_id"].duplicated().any():
        raise SystemExit("Two organisation names produced the same employer_id. Add an override in org_overrides.csv.")

    with_conflicts = dim[dim["attribute_conflicts"] != ""]
    report.add("Attribute conflicts", f"{len(with_conflicts)} employer(s) have rows that disagree. The chosen value is in dim_employer.")
    report.add("Attribute conflicts", "")
    report.add("Attribute conflicts", markdown_table(with_conflicts[["employer_name", "attribute_conflicts"]]))
    return dim


# ---------------------------------------------------------------- output tables


def build_engagement(signups, survey, was, sessions, peer, completed_rule, report):
    """One row per engagement event, from every source."""
    events = []

    def add(employer_id, when, precision, event_type, source, ref):
        events.append({
            "engagement_id": f"{event_type}-{ref}",
            "employer_id": employer_id,
            "date": when,
            "date_precision": precision if when else "",
            "event_type": event_type,
            "source": source,
            "source_ref": ref,
        })

    for row in signups.itertuples():
        add(row.employer_id, row.signup_month, "month", "account_signup", "signups", row.signup_id)
    for row in survey.itertuples():
        add(row.employer_id, row.date, "day", "survey_completed", "survey", row.response_id)
    for row in was.itertuples():
        add(row.employer_id, row.enquiry_date, "day", "was_request", "was", row.was_request_id)
    for row in sessions.itertuples():
        if row.session_date:
            add(row.employer_id, row.session_date, "day", "was_session_held", "was", row.session_id)

    # WAS completed, using the rule chosen in config.toml.
    for request_id, group in sessions.groupby("was_request_id"):
        first = group[group["session_number"] == 1]
        if completed_rule == "summary_1_sent":
            when = first["summary_sent_date"].iloc[0] if len(first) else None
        elif completed_rule == "session_1_held":
            when = first["session_date"].iloc[0] if len(first) else None
        elif completed_rule == "last_session_held":
            held = group["session_date"].dropna()
            when = max(held) if len(held) else None
        else:
            raise SystemExit(f"Unknown was.completed_rule '{completed_rule}' in config.toml.")
        if when and not pd.isna(when):
            add(group["employer_id"].iloc[0], when, "day", "was_completed", "was", request_id)

    for row in peer.itertuples():
        add(row.employer_id, row.interest_date, "day", "peer_mentoring_interest", "peer", row.peer_id)

    fact = pd.DataFrame(events, columns=COLUMNS["fact_engagement"])
    undated = fact[fact["date"].isna()]
    for event_type, n in undated["event_type"].value_counts().items():
        report.add("Warnings", f"- fact_engagement: {n} '{event_type}' event(s) have no date (counted, but not on monthly charts).")
    future = fact[fact["date"].notna() & (fact["date"] > date.today())]
    for event_type, n in future["event_type"].value_counts().items():
        report.add("Warnings", f"- fact_engagement: {n} '{event_type}' event(s) are dated after today.")
    return fact


def build_question_catalogue(maps, columns_map, answers, report):
    """One row per question and answer option, in form order."""
    questions = read_csv_text(maps / "survey_questions.csv")
    options = read_csv_text(maps / "survey_answers.csv")
    options["answer_order"] = options["answer_order"].astype(int)

    # Tick-box options or answers that turned up but are not in survey_answers.csv.
    known = set(zip(options["question_id"], options["answer"].str.casefold()))
    extra = []
    ticks = columns_map[columns_map["role"] == "tick"]
    seen = list(zip(ticks["question_id"], ticks["option_or_note"])) + list(zip(answers["question_id"], answers["answer"]))
    for qid, answer in seen:
        if (qid, answer.casefold()) not in known:
            known.add((qid, answer.casefold()))
            extra.append({"question_id": qid, "answer": answer, "answer_short": answer, "answer_order": 999})
    if extra:
        options = pd.concat([options, pd.DataFrame(extra)], ignore_index=True)

    catalogue = questions.merge(options, on="question_id", how="left")
    catalogue = catalogue.sort_values(["question_id", "answer_order"]).reset_index(drop=True)
    catalogue["answer_id"] = catalogue["question_id"] + "-" + (catalogue.groupby("question_id").cumcount() + 1).map("{:02d}".format)
    return catalogue[COLUMNS["question_catalogue"]]


def build_dim_date(*date_lists):
    """Calendar covering whole financial years from the earliest to the latest date."""
    all_dates = [d for dates in date_lists for d in dates if d and not pd.isna(d)]
    if not all_dates:
        return pd.DataFrame(columns=COLUMNS["dim_date"])
    first, last = min(all_dates), max(all_dates)
    start = date(first.year if first.month >= 4 else first.year - 1, 4, 1)
    end = date(last.year + 1 if last.month >= 4 else last.year, 3, 31)
    days = pd.date_range(start, end, freq="D")
    return pd.DataFrame({
        "date": days.date,
        "year": days.year,
        "month": days.month,
        "month_name": days.strftime("%B"),
        "month_start": days.to_period("M").start_time.date,
        "fin_year": [fin_year(d) for d in days.date],
        "fin_quarter": [f"Q{(d.month - 4) % 12 // 3 + 1}" for d in days],
    })


def survey_percentages(answers, question_id):
    """Figure 13 style numbers for one question.

    ticks       = respondents who chose the answer
    respondents = respondents who gave any answer to the question
    percent     = ticks / respondents * 100
    """
    rows = answers[answers["question_id"] == question_id]
    respondents = rows["response_id"].nunique()
    result = rows.groupby("answer")["response_id"].nunique().rename("ticks").reset_index()
    result["respondents"] = respondents
    result["percent"] = result["ticks"] / respondents * 100 if respondents else 0.0
    return result.sort_values("ticks", ascending=False).reset_index(drop=True)


def reconcile(signups, survey, was, report):
    """Compare the manual flags on Account signups with the real survey and WAS records."""
    for label, flag_column, other, other_name in (
        ("survey", "survey_flag", survey, "a survey response"),
        ("WAS", "was_flag", was, "a WAS record"),
    ):
        flagged = set(signups.loc[signups[flag_column] == True, "employer_id"])  # noqa: E712
        actual = set(other["employer_id"]) - {""}
        report.add(
            "Reconciliation",
            f"- {label}: {len(flagged)} employer(s) flagged 'Y' on Account signups, {len(actual)} with {other_name}; "
            f"{len(flagged & actual)} in both, {len(flagged - actual)} flagged with no record, "
            f"{len(actual - flagged)} with a record but no flag.",
        )


def write_csv(df, folder, name):
    """Write a table with its agreed columns. Dates come out as YYYY-MM-DD."""
    table = df.reindex(columns=COLUMNS[name]).copy()
    for column in table.columns:
        table[column] = table[column].map(lambda v: v.isoformat() if isinstance(v, (date, datetime)) else v)
    table.to_csv(folder / f"{name}.csv", index=False, encoding="utf-8")
    return len(table)


# ---------------------------------------------------------------- main


def run(config_path=HERE / "config.toml", output_folder=None):
    """Run the whole pipeline. Returns the output tables as a dict of DataFrames."""
    config_path = Path(config_path).resolve()
    with open(config_path, "rb") as f:
        cfg = tomllib.load(f)
    base = config_path.parent
    inputs = (base / cfg["paths"]["input_folder"]).resolve()
    maps = (base / cfg["paths"]["mappings_folder"]).resolve()
    out = Path(output_folder) if output_folder else (base / cfg["paths"]["output_folder"]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = Report()

    lookups = {name: load_lookup(maps / f"{name}.csv") for name in
               ("sector", "industry", "size_band", "sites_band", "was_duration", "was_topic")}
    overrides_table = read_csv_text(maps / "org_overrides.csv")
    overrides = {clean_text(r).casefold(): clean_text(c)
                 for r, c in zip(overrides_table["raw_name"], overrides_table["canonical_name"])}

    # 1. Read and clean each source.
    signups = load_signups(cfg["signups"], inputs, lookups, overrides, report)
    survey, answers, other_text, columns_map = load_survey(cfg["survey"], inputs, maps, lookups, overrides, report)
    was, sessions, topics = load_was(cfg["was"], inputs, lookups, overrides, report)
    peer = load_peer(cfg["peer"], inputs, lookups, overrides, report)

    # 2. One row per employer across all sources.
    attrs = ["org", "sector", "industry", "size_band", "sites_band"]
    org_rows = pd.concat(
        [frame[attrs].assign(source=source) for source, frame in
         (("signups", signups), ("survey", survey), ("was", was), ("peer", peer))],
        ignore_index=True,
    )
    org_rows["position"] = range(len(org_rows))
    dim_employer = build_dim_employer(org_rows, cfg["employers"]["source_priority"], report)

    repeated = signups["org"].str.casefold().value_counts()
    repeated = repeated[repeated > 1]
    report.add("Duplicates", f"- Account signups: {len(signups)} sign-up rows for {signups['org'].str.casefold().nunique()} organisations.")
    report.add("Duplicates", f"- {len(repeated)} organisation(s) appear more than once (each row kept as a user in fact_signup):")
    for key, n in repeated.items():
        name = dim_employer.loc[dim_employer["employer_name"].str.casefold() == key, "employer_name"].iloc[0]
        report.add("Duplicates", f"  - {name}: {n} rows")
    in_count = dim_employer[["in_signups", "in_survey", "in_was", "in_peer"]].sum(axis=1)
    report.add("Duplicates", f"- dim_employer: {len(dim_employer)} employers, {int((in_count > 1).sum())} found in more than one source.")
    not_in_signups = dim_employer.loc[~dim_employer["in_signups"], "employer_name"].tolist()
    if not_in_signups:
        report.add("Duplicates", f"- Employers not on Account signups (added from other files): {not_in_signups}")

    # 3. Attach employer_id to every source row.
    ids = dict(zip(dim_employer["employer_name"].str.casefold(), dim_employer["employer_id"]))
    for frame in (signups, survey, was, peer, sessions):
        if not frame.empty:
            frame["employer_id"] = frame["org"].str.casefold().map(ids).fillna("")

    # 4. Survey tables.
    responses = survey[["response_id", "employer_id", "date", "sector", "industry", "size_band", "sites_band"]].copy()
    employer_attrs = dim_employer.set_index("employer_id")
    filled = 0
    for attribute in ("sector", "industry", "size_band", "sites_band"):
        for i in responses.index:
            employer_id = responses.at[i, "employer_id"]
            if responses.at[i, attribute] == UNKNOWN and employer_id:
                responses.at[i, attribute] = employer_attrs.at[employer_id, attribute]
                filled += 1
    if filled:
        report.add("Survey checks", f"- {filled} blank response attribute(s) filled from dim_employer.")

    catalogue = build_question_catalogue(maps, columns_map, answers, report)
    fact_answers = answers.merge(responses[["response_id", "employer_id", "date"]], on="response_id")
    fact_answers = fact_answers.merge(
        catalogue[["question_id", "question", "answer_id", "answer"]], on=["question_id", "answer"], how="left"
    )
    report.add("Survey checks", f"- {len(responses)} response(s) gave {len(fact_answers)} answer row(s).")
    multi = catalogue.loc[catalogue["question_type"] == "multi", "question_id"].unique()
    for qid in multi:
        n = fact_answers.loc[fact_answers["question_id"] == qid, "response_id"].nunique()
        report.add("Survey checks", f"  - {qid}: {n} respondent(s)")

    # 5. Engagement events.
    engagement = build_engagement(signups, survey, was, sessions, peer, cfg["was"]["completed_rule"], report)
    reconcile(signups, survey, was, report)

    # 6. Calendar.
    session_dates = list(sessions["session_date"]) + list(sessions["summary_sent_date"]) if not sessions.empty else []
    flag_dates = [date.fromisoformat(d) for cell in pd.concat([signups["survey_dates"], signups["was_dates"]])
                  for d in cell.split(";") if d]
    dim_date = build_dim_date(engagement["date"], fact_answers["date"], session_dates, flag_dates)

    # 7. Write everything.
    tables = {
        "dim_employer": dim_employer,
        "fact_signup": signups,
        "fact_engagement": engagement,
        "dim_survey_response": responses,
        "fact_survey_answer": fact_answers,
        "question_catalogue": catalogue,
        "fact_was_session": sessions,
        "fact_was_session_topic": topics,
        "fact_event": pd.DataFrame(columns=COLUMNS["fact_event"]),  # no source yet
        "badges": pd.DataFrame(columns=COLUMNS["badges"]),  # no source yet
        "dim_date": dim_date,
    }
    if cfg["survey"]["keep_other_free_text"]:
        tables["survey_other_text"] = other_text
    else:
        stale = out / "survey_other_text.csv"
        if stale.exists():
            stale.unlink()

    counts = []
    for name, df in tables.items():
        counts.append((name, write_csv(df, out, name)))
        tables[name] = df.reindex(columns=COLUMNS[name])
    report.add("Outputs", markdown_table(pd.DataFrame(counts, columns=["table", "rows"])))
    report.add("Outputs", "")
    report.add("Outputs", "fact_engagement by event type:")
    report.add("Outputs", "")
    report.add("Outputs", markdown_table(engagement["event_type"].value_counts().rename_axis("event_type").reset_index(name="rows")))
    report.write(out / "data_quality_report.md")

    print(f"Wrote {len(tables)} tables and data_quality_report.md to {out}")
    for name, n in counts:
        print(f"  {name:24} {n:6} rows")
    return tables


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else HERE / "config.toml")
