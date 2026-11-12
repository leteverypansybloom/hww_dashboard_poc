// Validate the compiled publication graph without executing BigQuery SQL.
"use strict";

const fs = require("fs");
const assert = require("assert/strict");
const graph = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const errors = graph.graphErrors || {};
assert.equal((errors.compilationErrors || []).length, 0, "Compilation failed");
const gates = [
  "assert_loads_complete", "assert_mappings_valid", "assert_sources_not_empty",
  "assert_signup_months_valid", "assert_identifier_cases", "assert_keys_valid",
  "assert_row_counts_valid", "assert_loads_fresh",
  "assert_payload_keys_valid", "assert_no_duplicate_loads"
];
const tables = graph.tables || [];
const assertions = new Set((graph.assertions || []).map((action) => action.target.name));
for (const gate of gates) assert(assertions.has(gate), `Missing check: ${gate}`);
for (const table of tables.filter((action) => (action.tags || []).includes("gold"))) {
  assert(!table.disabled, `Gold table is disabled: ${table.target.name}`);
  const dependencies = new Set((table.dependencyTargets || []).map((target) => target.name));
  for (const gate of gates) {
    assert(dependencies.has(gate), `${table.target.name} does not wait for ${gate}`);
  }
}
assert.equal(tables.find((action) => action.target.name === "raw_latest_loads").type, "table");
// Gold publishes source text as it is: no check holds it back for
// looking like an email address, phone number or link.
for (const action of [...tables, ...(graph.assertions || [])]) {
  assert(
    !/@\[|\\\+44|https\?:/.test(action.query || ""),
    `${action.target.name} still filters contact details`
  );
}
// Every "Other (more info)" box loads into survey_other_text.
const otherText = tables.find((action) => action.target.name === "stg_survey_other_text");
assert(!otherText.disabled, "stg_survey_other_text is disabled");
assert(
  /Other \(more info\)/.test(otherText.query),
  "stg_survey_other_text reads no Other (more info) column"
);
const goldNames = tables
  .filter((action) => (action.tags || []).includes("gold"))
  .map((action) => action.target.name);
const record = (graph.operations || []).find(
  (action) => action.target.name === "record_published_loads"
);
assert(record, "Missing record_published_loads");
const recorded = new Set((record.dependencyTargets || []).map((target) => target.name));
for (const name of goldNames) {
  assert(recorded.has(name), `record_published_loads does not wait for ${name}`);
}
const rowCheck = graph.assertions.find((action) => action.target.name === "assert_row_counts_valid");
assert(
  rowCheck.dependencyTargets.some((target) => target.name === "published_loads"),
  "The row-count check must compare with the last published run"
);
console.log(`Validated ${tables.length} tables, ${assertions.size} assertions and ${gates.length} publication checks.`);
