// Settings and SQL snippets shared by the HWW models.
//
// Each function returns a BigQuery SQL expression as text, for use as
// ${hww.clean("Title")} in a .sqlx file. The rules they implement are
// numbered in docs/rules.md, and the Python they reproduce is in
// src/hww_dashboard/wrangle.py.

const reference_data = require("./reference_data");

const vars = dataform.projectConfig.vars;

// ---------------------------------------------------------------- settings

const SOURCES = ["signups", "survey", "was", "peer"];
const COMPLETED_RULES = ["summary_1_sent", "session_1_held", "last_session_held"];

const completedRule = vars.completed_rule;
if (!COMPLETED_RULES.includes(completedRule)) {
  throw new Error(
    `Unknown completed_rule '${completedRule}' in workflow_settings.yaml. ` +
      `Use one of ${COMPLETED_RULES.join(", ")}.`
  );
}

const sourcePriority = vars.source_priority.split(",").map((s) => s.trim());
if (
  sourcePriority.length !== SOURCES.length ||
  !SOURCES.every((source) => sourcePriority.includes(source))
) {
  throw new Error(
    "source_priority in workflow_settings.yaml must list each of " +
      `${SOURCES.join(", ")} once.`
  );
}

const keepOtherText = vars.keep_other_free_text === "true";
const allowEmpty = vars.allow_empty
  .split(",")
  .map((s) => s.trim())
  .filter((s) => s);
const maxRowDrop = Number(vars.max_row_drop);

// The gold dataset, and the checks that must pass before any gold
// table is rebuilt: if one fails, the gold tables keep the previous
// run's rows, as wrangle.py keeps the previous outputs when it stops.
const gold = vars.gold_dataset;
const stopChecks = [
  "assert_loads_complete",
  "assert_mappings_valid",
  "assert_sources_not_empty",
  "assert_signup_months_valid",
  "assert_identifier_cases",
];

// Raw table, landing folder workbook and sheet of each source, as in
// src/hww_dashboard/landing.py. The monitoring workbook loads two
// tables.
const RAW = {
  signups: { table: "hww_signups", file: vars.signups_file },
  survey: { table: "hww_survey", file: vars.signups_file },
  was: { table: "hww_was", file: vars.was_file },
  peer: { table: "hww_peer", file: vars.peer_file },
};

// Payload keys are the workbook headings exactly as py-common reads
// them: untrimmed, a blank heading named after its column letter. They
// match the contracts in src/hww_dashboard/landing.py.
const SIGNUPS = {
  month: "col_B",
  org: "Org (duplicates in red)",
  role: "Role (complete if duplicate org)",
  size: "Size",
  sector: "Sector",
  industry: "Industry",
  sites: "Number of sites",
  completedSurvey: "Completed survey?",
  requestedWas: "Requested WAS?",
};

const WAS = {
  id: "Participant ID",
  org: "Title",
  enquiryDate: "Date of Enquiry",
  fallbackEnquiryDate: "Date allocated to adviser",
  size: "Number of employees",
  sector: "Sector",
  industry: "Organisation Industry ",
  sites: "Number of sites",
  topicSeparator: ";#",
  // [[was.sessions]] in config.toml.
  sessions: [
    {
      number: 1,
      date: "Date of Session 1 ",
      duration: "Duration of session 1 ",
      summarySent: "Date summary sent to organisation",
      topics: "Topics discussed in session 1",
    },
    {
      number: 2,
      date: "Date of session 2",
      duration: "Duration of session 2",
      summarySent: "Date Summary 2 sent ",
      topics: "Topics discussed in session 2",
    },
    { number: 3, date: "Date of Session 3 " },
  ],
  // Every column the WAS contract loads, for the blank row check.
  loaded: [
    "Participant ID",
    "Date of Enquiry",
    "Date allocated to adviser",
    "Date of Session 1 ",
    "Date summary sent to organisation",
    "Date of session 2",
    "Date Summary 2 sent ",
    "Date of Session 3 ",
    "Title",
    "Number of employees",
    "Sector",
    "Organisation Industry ",
    "Number of sites",
    "Duration of session 1 ",
    "Topics discussed in session 1",
    "Duration of session 2",
    "Topics discussed in session 2",
  ],
};

const PEER = {
  id: "Participant ID",
  org: "Business Name",
  interestDate: "Date of expression of interest",
  size: "Business Size",
  sector: "Sector",
  industry: "Industry",
  loaded: [
    "Participant ID",
    "Business Name",
    "Business Size",
    "Sector",
    "Industry",
    "Date of expression of interest",
  ],
};

// survey_columns.csv, as the survey contract loads it: dropped columns
// are never loaded, nor "Other (more info)" text unless it is kept.
const surveyColumns = reference_data.surveyColumns.map((column, index) => ({
  ...column,
  position: index + 1,
}));
const surveyLoaded = surveyColumns.filter(
  (c) => c.role !== "drop" && (c.role !== "other_text" || keepOtherText)
);
const surveyQuestionColumns = surveyLoaded.filter((c) =>
  ["single", "tick", "other_text"].includes(c.role)
);

function surveyKey(role) {
  const found = surveyColumns.filter((c) => c.role === role);
  if (found.length !== 1) {
    throw new Error(
      `mappings/survey_columns.csv: give the role '${role}' exactly one column.`
    );
  }
  return found[0].payload_key;
}

const SURVEY = {
  responseId: surveyKey("response_id"),
  date: surveyKey("date"),
  org: surveyKey("org"),
  size: surveyKey("size"),
  sector: surveyKey("sector"),
  industry: surveyKey("industry"),
  sites: surveyKey("sites"),
};

// The column descriptions of a gold table, from its schema file in
// src/hww_dashboard/schema/.
function columns(table) {
  const described = {};
  for (const column of reference_data.schemas[table]) {
    described[column.name] = column.description;
  }
  return described;
}

// ---------------------------------------------------------------- SQL text

// A SQL string literal. Control, formatting and space characters other
// than a plain space are written as escapes, so they survive copying
// the compiled SQL.
function str(value) {
  const escaped = String(value)
    .replace(/\\/g, "\\\\")
    .replace(/'/g, "\\'")
    .replace(/[\u0000-\u001f\u007f-\u009f\p{Cf}\p{Z}]/gu, (c) => {
      if (c === " ") {
        return c;
      }
      const hex = c.codePointAt(0).toString(16).toUpperCase();
      return hex.length <= 4 ? `\\u${hex.padStart(4, "0")}` : `\\U${hex.padStart(8, "0")}`;
    });
  return `'${escaped}'`;
}

// What Python's str.isspace() counts as whitespace (docs/identifiers.md).
const WHITESPACE = String.raw`[\s\x{0B}\x{1C}-\x{1F}\x{85}\x{A0}\x{1680}\x{2000}-\x{200A}\x{2028}\x{2029}\x{202F}\x{205F}\x{3000}]+`;

// A payload value, by its key.
function field(key, payload = "payload") {
  return `${payload}[${str(key)}]`;
}

// R10: a JSON value as tidy text, or NULL when blank. Text is
// unchanged before tidying, a whole number written as a decimal loses
// its ".0", and TRUE and FALSE read as Python writes them.
function jsonText(json) {
  return String.raw`CASE JSON_TYPE(${json})
      WHEN 'string' THEN JSON_VALUE(${json})
      WHEN 'number' THEN REGEXP_REPLACE(JSON_VALUE(${json}), r'^(-?\d+)\.0+$', r'\1')
      WHEN 'boolean' THEN IF(BOOL(${json}), 'True', 'False')
    END`;
}

// R10: tidy a STRING expression: `_x000D_` and runs of whitespace
// become one space, the ends are trimmed, and blank becomes NULL.
function tidy(text) {
  return `NULLIF(TRIM(REGEXP_REPLACE(REPLACE(${text}, '_x000D_', ' '), r'${WHITESPACE}', ' '), ' '), '')`;
}

// R10: a payload value, tidied.
function clean(key, payload = "payload") {
  return tidy(jsonText(field(key, payload)));
}

// R11: a payload value as a DATE. py-common's contracts type every
// date column the models read, so a value is always ISO text
// ("2025-11-17" or "2025-11-17T09:30:00"); anything else reads as NULL.
function date(key, payload = "payload") {
  return String.raw`SAFE.PARSE_DATE('%Y-%m-%d', REGEXP_EXTRACT(JSON_VALUE(${field(key, payload)}), r'^(\d{4}-\d{2}-\d{2})(?:$|[T ])'))`;
}

// Whether any of a row's loaded values is non-blank (R06).
function anyValue(keys, payload = "payload") {
  return `(${keys.map((key) => `${clean(key, payload)} IS NOT NULL`).join("\n      OR ")})`;
}

// R60: the key organisation names are compared and hashed by
// (docs/identifiers.md): formatting characters removed, NFKC
// normalised and case folded, whitespace collapsed.
function nameKey(name) {
  return String.raw`NULLIF(TRIM(REGEXP_REPLACE(NORMALIZE_AND_CASEFOLD(REGEXP_REPLACE(${name}, r'\p{Cf}', ''), NFKC), r'${WHITESPACE}', ' '), ' '), '')`;
}

// R64: E and the first 8 hex digits of the MD5 of the name's key.
function employerId(key) {
  return `CONCAT('E', SUBSTR(TO_HEX(MD5(${key})), 1, 8))`;
}

// R12: the agreed value of a tidied text, from a LEFT JOIN of
// ref_lookups aliased `alias`: Unknown when blank or not mapped.
function band(alias) {
  return `COALESCE(${alias}.agreed_value, 'Unknown')`;
}

// The rank of a source in source_priority, 0 for the most trusted.
function priorityRank(sourceColumn) {
  return `CASE ${sourceColumn} ${sourcePriority
    .map((source, i) => `WHEN ${str(source)} THEN ${i}`)
    .join(" ")} END`;
}

// ---------------------------------------------------------------- flags

const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];

// R24: the yes/no part of "Y", "No", "Y (Dec)". NULL if unreadable.
function flag(text) {
  const word = `LOWER(TRIM(SPLIT(${text}, '(')[OFFSET(0)]))`;
  return `CASE
      WHEN ${text} IS NULL THEN FALSE
      WHEN ${word} IN ('n', 'no') THEN FALSE
      WHEN ${word} IN ('y', 'yes') THEN TRUE
    END`;
}

// The parts listed in a flag's brackets, split on "&", "," or " and ",
// with their position. \x1F can't survive tidy(), so it marks the
// splits.
function flagParts(text) {
  return String.raw`UNNEST(SPLIT(REGEXP_REPLACE(REGEXP_EXTRACT(${text}, r'\((.*)\)'), r'&|,| and ', '\x1F'), '\x1F')) AS part WITH OFFSET AS part_position`;
}

// R24: the first-of-month dates a "Y" flag lists, as
// "2025-12-01;2026-01-01", or NULL. A month without a year gets the
// year nearest the sign-up month; an exact six-month tie goes to the
// later year.
function flagDates(text, signupMonth) {
  const monthCase = `CASE LOWER(SUBSTR(word, 1, 3)) ${MONTHS.map(
    (m, i) => `WHEN '${m}' THEN ${i + 1}`
  ).join(" ")} END`;
  return String.raw`IF(${flag(text)} IS TRUE, (
      SELECT STRING_AGG(FORMAT_DATE('%F', month_date), ';' ORDER BY part_position)
      FROM (
        SELECT
          part_position,
          SAFE.DATE(
            CASE
              WHEN year_number IS NOT NULL
                THEN IF(year_number < 100, year_number + 2000, year_number)
              WHEN month_number - EXTRACT(MONTH FROM ${signupMonth}) > 6
                THEN EXTRACT(YEAR FROM ${signupMonth}) - 1
              WHEN month_number - EXTRACT(MONTH FROM ${signupMonth}) <= -6
                THEN EXTRACT(YEAR FROM ${signupMonth}) + 1
              ELSE EXTRACT(YEAR FROM ${signupMonth})
            END,
            month_number,
            1
          ) AS month_date
        FROM (
          SELECT
            part_position,
            ${monthCase} AS month_number,
            SAFE_CAST(year_text AS INT64) AS year_number
          FROM (
            SELECT
              part_position,
              REGEXP_EXTRACT(TRIM(part), r'^([A-Za-z]+)\.?\s*(?:\d{2}|\d{4})?$') AS word,
              REGEXP_EXTRACT(TRIM(part), r'^[A-Za-z]+\.?\s*(\d{2}|\d{4})?$') AS year_text
            FROM ${flagParts(text)}
            WHERE TRIM(part) != ''
          )
        )
      )
      WHERE month_date IS NOT NULL
    ), NULL)`;
}

// How many of a "Y" flag's bracketed parts couldn't be read as a
// month (reported, as wrangle.py's "Free-text flags" notes).
function flagUnreadParts(text, signupMonth) {
  return `IF(${flag(text)} IS TRUE, (
      SELECT COUNT(*) FROM ${flagParts(text)} WHERE TRIM(part) != ''
    ) - IFNULL(ARRAY_LENGTH(SPLIT(${flagDates(text, signupMonth)}, ';')), 0), 0)`;
}

// ---------------------------------------------------------------- loads

// The rows of a source's selected load: the newest committed load of
// its agreed file in py-common's audit table, as
// src/hww_dashboard/landed.py reads it. An upload with no rows is a
// load too, so it is never mistaken for the one before.
function latestRows(source, rawRef, loadsRef) {
  return `(
    SELECT raw.*
    FROM ${rawRef} AS raw
    JOIN ${loadsRef} AS selected
      ON selected.raw_table = ${str(RAW[source].table)}
      AND raw.source_generation = selected.source_version
      AND raw.ingested_at = selected.loaded_at
  )`;
}

module.exports = {
  SOURCES,
  RAW,
  SIGNUPS,
  WAS,
  PEER,
  SURVEY,
  allowEmpty,
  anyValue,
  band,
  clean,
  columns,
  completedRule,
  date,
  employerId,
  field,
  flag,
  flagDates,
  flagUnreadParts,
  gold,
  keepOtherText,
  latestRows,
  maxRowDrop,
  nameKey,
  priorityRank,
  sourcePriority,
  stopChecks,
  str,
  surveyColumns,
  surveyLoaded,
  surveyQuestionColumns,
  tidy,
};
