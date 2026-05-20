from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyspark.sql import SparkSession


def export_table(
    spark: SparkSession,
    table_name: str,
    output_path: str,
    file_format: str = "parquet",
    where_clause: str = "",
) -> None:
    df = spark.table(table_name)
    if where_clause:
        df = df.where(where_clause)
    df.write.format(file_format).mode("overwrite").save(output_path)
