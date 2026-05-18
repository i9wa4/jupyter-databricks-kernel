import main

main.run(
    table_name="hive_metastore.default.test_export",
    output_path="dbfs:/tmp/table-exporter-test/output",
    file_format="json",
    where_clause="",
)
