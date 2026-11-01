// Acceptance checks: compare every gold table with the table of the
// same name in expected_dataset, both ways and by row count, as in
// docs/output_contract.md, "Comparing another implementation". Built
// only when expected_dataset is set in workflow_settings.yaml (or a
// workspace's compilation overrides).
//
// Load the expected tables first, from tests/golden/*.csv or
// tests/scenarios/expected/*.csv, with their schema files; docs/dataform.md
// has the commands.

const expectedDataset = dataform.projectConfig.vars.expected_dataset;
const expectedTables = dataform.projectConfig.vars.expected_tables
  .split(",")
  .map((s) => s.trim())
  .filter((s) => s);

if (expectedDataset) {
  const tables = Object.keys(reference_data.schemas).filter(
    (table) =>
      (table !== "survey_other_text" || hww.keepOtherText) &&
      (!expectedTables.length || expectedTables.includes(table))
  );
  for (const table of tables) {
    const columns = reference_data.schemas[table].map((c) => c.name).join(", ");
    assert(`acceptance_${table}`, {
      description: `${table} matches ${expectedDataset}.${table} exactly`,
      tags: ["acceptance"],
    }).query((ctx) => {
      const gold = ctx.ref({ schema: hww.gold, name: table });
      const expected = `\`${ctx.database()}.${expectedDataset}.${table}\``;
      return `WITH gold AS (SELECT ${columns} FROM ${gold}),
expected AS (SELECT ${columns} FROM ${expected})

SELECT 'expected, not in gold' AS problem, TO_JSON_STRING(difference) AS row_values
FROM (SELECT * FROM expected EXCEPT DISTINCT SELECT * FROM gold) AS difference
UNION ALL
SELECT 'in gold, not expected', TO_JSON_STRING(difference)
FROM (SELECT * FROM gold EXCEPT DISTINCT SELECT * FROM expected) AS difference
UNION ALL
SELECT FORMAT('row counts differ: gold %d, expected %d', g, e), NULL
FROM (SELECT (SELECT COUNT(*) FROM gold) AS g, (SELECT COUNT(*) FROM expected) AS e)
WHERE g != e`;
    });
  }
}
