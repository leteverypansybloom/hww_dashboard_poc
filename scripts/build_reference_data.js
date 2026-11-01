// Build includes/reference_data.js from the project's own files.
//
// Dataform can't read CSV or JSON files, so the mapping CSVs, the
// output table schemas and the identifier test cases are copied into
// one JavaScript file that the models read at compile time. The
// source files stay the only place to edit:
//
//   node scripts/build_reference_data.js           rewrite the file
//   node scripts/build_reference_data.js --check   fail if it is stale
//
// Run it from the dataform folder after changing anything in
// mappings/, src/hww_dashboard/schema/ or
// tests/data/identifier_cases.json, and commit both.

"use strict";

const fs = require("fs");
const path = require("path");

const here = path.resolve(__dirname, "..");
const project = path.resolve(here, "..");
const output = path.join(here, "includes", "reference_data.js");

const LOOKUPS = [
  "sector",
  "industry",
  "size_band",
  "sites_band",
  "was_duration",
  "was_topic",
];

// The tables of docs/output_contract.md, in its order.
const TABLES = [
  "dim_employer",
  "fact_signup",
  "fact_engagement",
  "dim_survey_response",
  "fact_survey_answer",
  "survey_other_text",
  "question_catalogue",
  "fact_was_session",
  "fact_was_session_topic",
  "fact_event",
  "badges",
  "dim_date",
];

// Parse CSV text: quoted fields, doubled quotes, CRLF or LF endings
// and a leading byte-order mark, as Excel saves it.
function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;
  let i = text.charCodeAt(0) === 0xfeff ? 1 : 0;
  for (; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') {
        field += '"';
        i++;
      } else if (c === '"') {
        quoted = false;
      } else {
        field += c;
      }
    } else if (c === '"') {
      quoted = true;
    } else if (c === ",") {
      row.push(field);
      field = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") {
        i++;
      }
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += c;
    }
  }
  if (field !== "" || row.length) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}

// Read a mapping CSV as objects keyed by its headings, with the CSV
// line number of each row (the header is line 1).
function readCsv(name, required) {
  const file = path.join(project, "mappings", name);
  const [header, ...rows] = parseCsv(fs.readFileSync(file, "utf8"));
  for (const column of required) {
    if (!header.includes(column)) {
      throw new Error(`mappings/${name} has no ${column} column`);
    }
  }
  return rows
    .filter((cells) => cells.some((cell) => cell !== ""))
    .map((cells, index) => {
      if (cells.length !== header.length) {
        throw new Error(`mappings/${name} line ${index + 2}: wrong field count`);
      }
      const row = { line: index + 2 };
      header.forEach((column, j) => {
        row[column] = cells[j];
      });
      return row;
    });
}

// py-common's name for a heading wrangle.py numbers like pandas:
// "Other (more info).1" is the payload key "Other (more info)_2"
// (py_common_name in src/hww_dashboard/landing.py).
function payloadKey(heading) {
  const repeat = /^(.*)\.(\d+)$/.exec(heading);
  if (repeat && Number(repeat[2]) >= 1) {
    return `${repeat[1]}_${Number(repeat[2]) + 1}`;
  }
  return heading;
}

function build() {
  const lookups = {};
  for (const name of LOOKUPS) {
    lookups[name] = readCsv(`${name}.csv`, ["raw_value", "agreed_value"]);
  }
  const schemas = {};
  for (const table of TABLES) {
    const file = path.join(
      project,
      "src",
      "hww_dashboard",
      "schema",
      `${table}.json`
    );
    schemas[table] = JSON.parse(fs.readFileSync(file, "utf8")).map(
      (column) => ({
        name: column.name,
        type: column.type,
        mode: column.mode || "NULLABLE",
        description: column.description || "",
      })
    );
  }
  const cases = JSON.parse(
    fs.readFileSync(
      path.join(project, "tests", "data", "identifier_cases.json"),
      "utf8"
    )
  );
  const data = {
    lookups,
    agreedValues: readCsv("agreed_values.csv", ["dimension", "agreed_value"]),
    orgOverrides: readCsv("org_overrides.csv", ["raw_name", "canonical_name"]),
    surveyColumns: readCsv("survey_columns.csv", [
      "column",
      "role",
      "question_id",
      "option_or_note",
    ]).map((row) => ({ ...row, payload_key: payloadKey(row.column) })),
    surveyQuestions: readCsv("survey_questions.csv", [
      "question_id",
      "question",
      "question_short",
      "question_type",
    ]),
    surveyAnswers: readCsv("survey_answers.csv", [
      "question_id",
      "answer",
      "answer_short",
      "answer_order",
    ]),
    surveyAnswerTranslations: readCsv("survey_answer_translations.csv", [
      "question_id",
      "raw_answer",
      "answer",
    ]),
    schemas,
    identifierCases: cases.map((c) => ({
      raw: c.raw,
      key: c.key,
      employer_id: c.employer_id,
    })),
  };
  return (
    "// Built by scripts/build_reference_data.js from mappings/*.csv,\n" +
    "// src/hww_dashboard/schema/*.json and\n" +
    "// tests/data/identifier_cases.json. Edit those files and run the\n" +
    "// script; don't edit this file.\n\n" +
    `module.exports = ${JSON.stringify(data, null, 2)};\n`
  );
}

const text = build();
if (process.argv.includes("--check")) {
  const current = fs.existsSync(output) ? fs.readFileSync(output, "utf8") : "";
  if (current.replace(/\r\n/g, "\n") !== text) {
    console.error(
      "includes/reference_data.js is out of date. Run " +
        "node scripts/build_reference_data.js and commit it."
    );
    process.exit(1);
  }
  console.log("includes/reference_data.js is up to date.");
} else {
  fs.writeFileSync(output, text);
  console.log(`Wrote ${path.relative(here, output)}`);
}
