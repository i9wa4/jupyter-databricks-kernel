from __future__ import annotations

from typing import TYPE_CHECKING

from common.params import get_param, get_required_param
from common.validator import validate_output_path, validate_table_name
from processors.exporter import export_table

if TYPE_CHECKING:
    from pyspark.sql import SparkSession


def _get_active_spark() -> SparkSession:
    from pyspark.sql import SparkSession

    spark = SparkSession.getActiveSession()
    if spark is None:
        raise RuntimeError("No active SparkSession")
    return spark


def run(
    table_name: str,
    output_path: str,
    file_format: str = "json",
    where_clause: str = "",
    spark: SparkSession | None = None,
) -> None:
    """Export an existing table to DBFS/S3.

    Suitable for `uv run run-ipynb` and interactive Databricks notebook use.
    """
    table_name = validate_table_name(table_name)
    output_path = validate_output_path(output_path)
    spark = spark or _get_active_spark()

    export_table(spark, table_name, output_path, file_format, where_clause)
    print(f"Exported {table_name} to {output_path} as {file_format}")


def main(
    table_name: str | None = None,
    output_path: str | None = None,
    file_format: str | None = None,
    where_clause: str | None = None,
) -> None:
    run(
        table_name=table_name or get_required_param("table_name"),
        output_path=output_path or get_required_param("output_path"),
        file_format=file_format or get_param("file_format", "json"),
        where_clause=where_clause or get_param("where_clause", ""),
    )


if __name__ == "__main__":
    main()
