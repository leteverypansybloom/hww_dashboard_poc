// Checks on each gold table against docs/output_contract.md and its
// schema file in src/hww_dashboard/schema/ (R80, R81). For each table,
// gold_<table>_contract returns one row per problem:
//
//   - a column missing, out of order or of another type than the
//     schema file says;
//   - a required column that is NULL;
//   - a repeated key;
//   - an email address, UK phone number, IPv4 address or web link in a
//     text column (where, never the value).
//
// A check reads only its own table, so a gold table built from
// another waits for that table's check.

const KEYS = {
  dim_employer: ["employer_id"],
  fact_signup: ["signup_id"],
  fact_engagement: ["engagement_id"],
  dim_survey_response: ["response_id"],
  fact_survey_answer: ["response_id", "question_id", "answer"],
  survey_other_text: ["response_id", "question_id"],
  question_catalogue: ["answer_id"],
  fact_was_session: ["session_id"],
  fact_was_session_topic: ["session_id", "topic"],
  dim_date: ["date"],
};

// The same pattern wrangle.check_public_text uses.
const CONTACT_DETAILS = String.raw`[\w.+-]+@[\w-]+\.[\w.]+|(?:\+44|\b0)(?:[\s()-]*\d){9,10}\b|\b(?:\d{1,3}\.){3}\d{1,3}\b|https?://`;

const tables = Object.keys(reference_data.schemas).filter(
  (table) => table !== "survey_other_text" || hww.keepOtherText
);

for (const table of tables) {
  const schema = reference_data.schemas[table];
  const key = KEYS[table];
  assert(`gold_${table}_contract`, {
    description: `${table}: columns as its schema file, required columns never NULL, a unique key and no contact details`,
    tags: ["gold"],
  }).query((ctx) => {
    const target = ctx.ref({ schema: hww.gold, name: table });
    const information = target.replace(/\.[^.`]+`$/, ".INFORMATION_SCHEMA.COLUMNS`");
    const expected = schema
      .map((c, i) => `(${i + 1}, ${hww.str(c.name)}, ${hww.str(c.type)})`)
      .join(",\n    ");
    const checks = [
      `SELECT CONCAT('column ', column_name, ' ', data_type, ' at position ', CAST(ordinal_position AS STRING), ' is missing or different') AS problem, NULL AS row_count
FROM expected
LEFT JOIN actual USING (ordinal_position, column_name, data_type)
WHERE actual.column_name IS NULL`,
      `SELECT CONCAT('column ', column_name, ' is not in the schema file'), NULL
FROM actual
LEFT JOIN expected USING (ordinal_position, column_name, data_type)
WHERE expected.column_name IS NULL`,
    ];
    for (const column of schema.filter((c) => c.mode === "REQUIRED")) {
      checks.push(
        `SELECT ${hww.str(`${column.name} is NULL`)}, COUNT(*)
FROM ${target}
WHERE ${column.name} IS NULL
HAVING COUNT(*) > 0`
      );
    }
    if (key) {
      checks.push(
        `SELECT ${hww.str(`${key.join(", ")} repeated`)}, COUNT(*)
FROM (
  SELECT ${key.join(", ")}
  FROM ${target}
  GROUP BY ${key.join(", ")}
  HAVING COUNT(*) > 1
)
HAVING COUNT(*) > 0`
      );
    }
    for (const column of schema.filter((c) => c.type === "STRING")) {
      checks.push(
        `SELECT ${hww.str(`contact details in ${column.name}`)}, COUNT(*)
FROM ${target}
WHERE REGEXP_CONTAINS(${column.name}, r'${CONTACT_DETAILS}')
HAVING COUNT(*) > 0`
      );
    }
    return `WITH expected AS (
  SELECT *
  FROM UNNEST(ARRAY<STRUCT<ordinal_position INT64, column_name STRING, data_type STRING>>[
    ${expected}
  ])
),

actual AS (
  SELECT ordinal_position, column_name, data_type
  FROM ${information}
  WHERE table_name = ${hww.str(table)}
)

${checks.join("\nUNION ALL\n")}`;
  });
}
