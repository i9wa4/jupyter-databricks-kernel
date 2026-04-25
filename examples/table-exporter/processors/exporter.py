from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyspark.sql import SparkSession


def export_table(
    spark: SparkSession,
    table_name: str,
    output_path: str,
    file_format: str = "parquet",
) -> None:
    df = spark.table(table_name)
    df.write.format(file_format).mode("overwrite").save(output_path)
