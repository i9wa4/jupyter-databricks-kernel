from __future__ import annotations

import re


def validate_s3_path(path: str) -> str:
    if not re.match(r"^s3://[a-zA-Z0-9.\-_]+(/.*)?$", path):
        raise ValueError(f"Invalid S3 path: {path!r}")
    return path


def validate_table_name(table_name: str) -> str:
    stripped = table_name.strip("`")
    parts = stripped.split(".")
    if len(parts) != 3:
        raise ValueError(
            f"table_name must be catalog.schema.table, got: {table_name!r}"
        )
    return table_name
