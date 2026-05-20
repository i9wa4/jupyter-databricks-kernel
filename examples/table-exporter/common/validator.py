from __future__ import annotations

import re

_IDENTIFIER_PATTERN = re.compile(r"(?:`[^`]+`|[A-Za-z_][A-Za-z0-9_]*)")
_S3_PATH_PATTERN = re.compile(r"^s3://[a-zA-Z0-9.\-_]+(?:/.*)?$")
_DBFS_URI_PATTERN = re.compile(r"^dbfs:/.*$")
_DBFS_FUSE_PATTERN = re.compile(r"^/dbfs/.*$")


def validate_output_path(path: str) -> str:
    if not (
        _S3_PATH_PATTERN.match(path)
        or _DBFS_URI_PATTERN.match(path)
        or _DBFS_FUSE_PATTERN.match(path)
    ):
        raise ValueError(f"Invalid output path: {path!r}")
    return path


def validate_s3_path(path: str) -> str:
    return validate_output_path(path)


def validate_table_name(table_name: str) -> str:
    normalized = table_name.strip()
    parts = normalized.split(".")
    if len(parts) != 3 or any(
        _IDENTIFIER_PATTERN.fullmatch(part) is None for part in parts
    ):
        raise ValueError(
            f"table_name must be catalog.schema.table, got: {table_name!r}"
        )
    return normalized
