// Bronze: the raw JSON tables py-common loads, one per source, and
// its audit table, which records every committed load
// (py-common's docs/RAW_TABLE_LAYOUT.md).

const rawDataset = dataform.projectConfig.vars.raw_dataset;

for (const source of hww.SOURCES) {
  declare({
    schema: rawDataset,
    name: hww.RAW[source].table,
    description: `py-common raw table for ${source}: one JSON payload per sheet row`,
  });
}

declare({
  schema: rawDataset,
  name: "audit",
  description: "py-common audit table: one row per load of each raw table",
});
