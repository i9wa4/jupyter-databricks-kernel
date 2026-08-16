from __future__ import annotations

import os


def get_required_param(name: str) -> str:
    """Get a required parameter from dbutils widgets or environment variable."""
    try:
        databricks_utils = dbutils  # type: ignore[name-defined]
    except NameError:
        value = os.environ.get(name.upper(), "")
    else:
        value = databricks_utils.widgets.get(name)
    if not value:
        raise ValueError(f"Required parameter '{name}' is not set")
    return value


def get_param(name: str, default: str = "") -> str:
    """Get an optional parameter from dbutils widgets or environment variable."""
    try:
        databricks_utils = dbutils  # type: ignore[name-defined]
    except NameError:
        return os.environ.get(name.upper(), default)
    return databricks_utils.widgets.get(name)
