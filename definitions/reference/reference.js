// Reference tables built from the project's mappings/*.csv, by way of
// includes/reference_data.js. Values are kept as the CSV holds them;
// the *_key columns are what the models match on (R09, R12).

const data = reference_data;

// A table from rows of plain values, typed even when there are none.
function values(columns, rows) {
  const type = columns.map(([name, sqlType]) => `${name} ${sqlType}`).join(", ");
  const literals = rows.map(
    (row) =>
      "(" +
      columns
        .map(([name, sqlType]) =>
          sqlType === "INT64" ? String(row[name]) : hww.str(row[name])
        )
        .join(", ") +
      ")"
  );
  return `SELECT * FROM UNNEST(ARRAY<STRUCT<${type}>>[\n  ${literals.join(",\n  ")}\n])`;
}

const lookupRows = [];
for (const [dimension, rows] of Object.entries(data.lookups)) {
  for (const row of rows) {
    lookupRows.push({ dimension, ...row });
  }
}

publish("ref_lookup_rows", {
  type: "table",
  description:
    "Every row of the band and WAS mappings (mappings/<dimension>.csv): " +
    "raw_key is the tidied, lower-case raw value; agreed_value the tidied target",
}).query(
  (ctx) => `
SELECT
  dimension,
  line,
  raw_value,
  LOWER(${hww.tidy("raw_value")}) AS raw_key,
  ${hww.tidy("agreed_value_text")} AS agreed_value
FROM (
${values(
  [
    ["dimension", "STRING"],
    ["line", "INT64"],
    ["raw_value", "STRING"],
    ["agreed_value_text", "STRING"],
  ],
  lookupRows.map((r) => ({ ...r, agreed_value_text: r.agreed_value }))
)}
)`
);

publish("ref_lookups", {
  type: "table",
  description:
    "R12: one agreed value per dimension and raw_key, for the models' " +
    "joins. assert_mappings_valid stops the run if the rows disagree",
}).query(
  (ctx) => `
SELECT dimension, raw_key, agreed_value
FROM ${ctx.ref("ref_lookup_rows")}
WHERE raw_key IS NOT NULL AND agreed_value IS NOT NULL
QUALIFY ROW_NUMBER() OVER (PARTITION BY dimension, raw_key ORDER BY line) = 1`
);

publish("ref_agreed_values", {
  type: "table",
  description: "The agreed values of each dimension (mappings/agreed_values.csv)",
}).query(
  (ctx) => `
SELECT dimension_text AS dimension, line, ${hww.tidy("value_text")} AS agreed_value
FROM (
${values(
  [
    ["dimension_text", "STRING"],
    ["line", "INT64"],
    ["value_text", "STRING"],
  ],
  data.agreedValues.map((r) => ({
    dimension_text: r.dimension,
    line: r.line,
    value_text: r.agreed_value,
  }))
)}
)`
);

publish("ref_org_overrides", {
  type: "table",
  description:
    "Organisation name overrides (mappings/org_overrides.csv), tidied, " +
    "with the key of the raw name",
}).query(
  (ctx) => `
SELECT
  line,
  ${hww.tidy("raw_name")} AS raw_name,
  ${hww.nameKey(hww.tidy("raw_name"))} AS raw_key,
  ${hww.tidy("canonical_name")} AS canonical_name
FROM (
${values(
  [
    ["line", "INT64"],
    ["raw_name", "STRING"],
    ["canonical_name", "STRING"],
  ],
  data.orgOverrides
)}
)`
);

publish("ref_survey_columns", {
  type: "table",
  description:
    "What each Survey info column is (mappings/survey_columns.csv), with " +
    "the payload key py-common loads it under",
}).query(
  (ctx) => `
${values(
  [
    ["position", "INT64"],
    ["column_name", "STRING"],
    ["payload_key", "STRING"],
    ["role", "STRING"],
    ["question_id", "STRING"],
    ["option_or_note", "STRING"],
  ],
  hww.surveyColumns.map((c) => ({ ...c, column_name: c.column }))
)}`
);

publish("ref_survey_questions", {
  type: "table",
  description: "Survey questions (mappings/survey_questions.csv)",
}).query(
  (ctx) => `
${values(
  [
    ["line", "INT64"],
    ["question_id", "STRING"],
    ["question", "STRING"],
    ["question_short", "STRING"],
    ["question_type", "STRING"],
  ],
  data.surveyQuestions
)}`
);

publish("ref_survey_answers", {
  type: "table",
  description:
    "Survey answer options in form order (mappings/survey_answers.csv); " +
    "answer_key is the lower-case answer",
}).query(
  (ctx) => `
SELECT
  line,
  question_id,
  answer,
  LOWER(answer) AS answer_key,
  answer_short,
  answer_order_text,
  SAFE_CAST(answer_order_text AS INT64) AS answer_order
FROM (
${values(
  [
    ["line", "INT64"],
    ["question_id", "STRING"],
    ["answer", "STRING"],
    ["answer_short", "STRING"],
    ["answer_order_text", "STRING"],
  ],
  data.surveyAnswers.map((r) => ({ ...r, answer_order_text: r.answer_order }))
)}
)`
);

publish("ref_survey_answer_translation_rows", {
  type: "table",
  description:
    "Every row of mappings/survey_answer_translations.csv (Welsh survey " +
    "answers in English); raw_key is the tidied, lower-case Welsh answer",
}).query(
  (ctx) => `
SELECT
  line,
  question_id,
  raw_answer,
  LOWER(${hww.tidy("raw_answer")}) AS raw_key,
  ${hww.tidy("answer_text")} AS answer
FROM (
${values(
  [
    ["line", "INT64"],
    ["question_id", "STRING"],
    ["raw_answer", "STRING"],
    ["answer_text", "STRING"],
  ],
  data.surveyAnswerTranslations.map((r) => ({ ...r, answer_text: r.answer }))
)}
)`
);

publish("ref_survey_answer_translations", {
  type: "table",
  description:
    "R33: one English answer per question and Welsh raw_key, for the " +
    "models' joins. assert_mappings_valid stops the run if the rows disagree",
}).query(
  (ctx) => `
SELECT question_id, raw_key, answer
FROM ${ctx.ref("ref_survey_answer_translation_rows")}
WHERE raw_key IS NOT NULL AND answer IS NOT NULL
QUALIFY ROW_NUMBER() OVER (PARTITION BY question_id, raw_key ORDER BY line) = 1`
);
