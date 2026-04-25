from __future__ import annotations

from common.params import get_param, get_required_param
from common.validator import validate_s3_path, validate_table_name
from processors.exporter import export_table


def main() -> None:
    table_name = validate_table_name(get_required_param("table_name"))
    output_path = validate_s3_path(get_required_param("output_path"))
    file_format = get_param("file_format", "parquet")

    export_table(spark, table_name, output_path, file_format)  # type: ignore[name-defined]  # noqa: F821
    print(f"Exported {table_name} to {output_path} as {file_format}")


if __name__ == "__main__":
    main()
