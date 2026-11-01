// fact_event and badges have no source yet. wrangle.py writes them
// empty with their columns, so they are published empty with the
// columns of their schema files.

const TYPES = { STRING: "STRING", DATE: "DATE", INT64: "INT64", BOOL: "BOOL" };

for (const table of ["fact_event", "badges"]) {
  const selected = reference_data.schemas[table]
    .map((column) => `CAST(NULL AS ${TYPES[column.type]}) AS ${column.name}`)
    .join(",\n  ");
  publish(table, {
    type: "table",
    schema: hww.gold,
    description: `Placeholder for ${table}: no source yet, so it has no rows`,
    tags: ["gold"],
    columns: hww.columns(table),
  }).query(`SELECT\n  ${selected}\nLIMIT 0`);
}
