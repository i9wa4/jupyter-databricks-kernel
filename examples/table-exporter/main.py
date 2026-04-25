from __future__ import annotations

from common.validator import validate_s3_path, validate_table_name
from processors.exporter import export_table


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
