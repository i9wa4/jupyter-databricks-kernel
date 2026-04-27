from __future__ import annotations

from common.validator import validate_s3_path, validate_table_name
from processors.exporter import export_table


def run(
    table_name: str,
    output_path: str,
    file_format: str = "json",
    where_clause: str = "",
) -> None:
    """Export a table to DBFS/S3. Creates a test table if it does not exist.

    Suitable for `uv run run-ipynb` and interactive Databricks notebook use.
    """
    spark.sql("CREATE DATABASE IF NOT EXISTS default")  # type: ignore[name-defined]  # noqa: F821
    spark.sql(f"DROP TABLE IF EXISTS {table_name}")  # type: ignore[name-defined]  # noqa: F821
    spark.sql(  # type: ignore[name-defined]  # noqa: F821
        f"CREATE TABLE {table_name} USING DELTA "
        "AS SELECT id, name FROM VALUES (1, 'Alice'), (2, 'Bob') t(id, name)"
    )

    df = spark.table(table_name)  # type: ignore[name-defined]  # noqa: F821
    if where_clause:
        df = df.where(where_clause)
    df.write.format(file_format).mode("overwrite").save(output_path)
    print(f"Exported {table_name} to {output_path} as {file_format}")


def main(
    table_name: str = "",
    output_path: str = "",
    file_format: str = "parquet",
    where_clause: str = "",
) -> None:
    table_name = validate_table_name(table_name)
    output_path = validate_s3_path(output_path)

    export_table(spark, table_name, output_path, file_format, where_clause)  # type: ignore[name-defined]  # noqa: F821
    print(f"Exported {table_name} to {output_path} as {file_format}")


if __name__ == "__main__":
    main()
