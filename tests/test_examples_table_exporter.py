from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

EXAMPLE_DIR = Path(__file__).parents[1] / "examples" / "table-exporter"


@pytest.fixture
def table_exporter_modules() -> tuple[object, object]:
    sys.path.insert(0, str(EXAMPLE_DIR))
    try:
        main = importlib.import_module("main")
        validator = importlib.import_module("common.validator")
        yield main, validator
    finally:
        sys.path.remove(str(EXAMPLE_DIR))
        for name in (
            "main",
            "common",
            "common.params",
            "common.validator",
            "processors",
            "processors.exporter",
        ):
            sys.modules.pop(name, None)


class FakeWriter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def format(self, file_format: str) -> FakeWriter:
        self.calls.append(("format", file_format))
        return self

    def mode(self, mode: str) -> FakeWriter:
        self.calls.append(("mode", mode))
        return self

    def save(self, output_path: str) -> None:
        self.calls.append(("save", output_path))


class FakeDataFrame:
    def __init__(self) -> None:
        self.where_clause = ""
        self.writer = FakeWriter()

    @property
    def write(self) -> FakeWriter:
        return self.writer

    def where(self, where_clause: str) -> FakeDataFrame:
        self.where_clause = where_clause
        return self


class FakeSpark:
    def __init__(self) -> None:
        self.table_name = ""
        self.dataframe = FakeDataFrame()

    def table(self, table_name: str) -> FakeDataFrame:
        self.table_name = table_name
        return self.dataframe

    def sql(self, query: str) -> None:
        raise AssertionError(f"run() must not execute DDL/DML: {query}")


def test_run_exports_existing_table_without_ddl(table_exporter_modules) -> None:
    main, _validator = table_exporter_modules
    spark = FakeSpark()

    main.run(
        table_name="catalog.schema.table",
        output_path="dbfs:/tmp/table-exporter/output",
        file_format="json",
        where_clause="id = 1",
        spark=spark,
    )

    assert spark.table_name == "catalog.schema.table"
    assert spark.dataframe.where_clause == "id = 1"
    assert spark.dataframe.writer.calls == [
        ("format", "json"),
        ("mode", "overwrite"),
        ("save", "dbfs:/tmp/table-exporter/output"),
    ]


def test_main_reads_environment_parameters(monkeypatch, table_exporter_modules) -> None:
    main, _validator = table_exporter_modules
    calls: list[dict[str, str]] = []

    monkeypatch.setenv("TABLE_NAME", "catalog.schema.table")
    monkeypatch.setenv("OUTPUT_PATH", "s3://bucket/path")
    monkeypatch.setenv("FILE_FORMAT", "parquet")
    monkeypatch.setenv("WHERE_CLAUSE", "dt = '2026-05-18'")
    monkeypatch.setattr(main, "run", lambda **kwargs: calls.append(kwargs))

    main.main()

    assert calls == [
        {
            "table_name": "catalog.schema.table",
            "output_path": "s3://bucket/path",
            "file_format": "parquet",
            "where_clause": "dt = '2026-05-18'",
        }
    ]


def test_main_defaults_file_format_to_json(monkeypatch, table_exporter_modules) -> None:
    main, _validator = table_exporter_modules
    calls: list[dict[str, str]] = []

    monkeypatch.setenv("TABLE_NAME", "catalog.schema.table")
    monkeypatch.setenv("OUTPUT_PATH", "s3://bucket/path")
    monkeypatch.delenv("FILE_FORMAT", raising=False)
    monkeypatch.setattr(main, "run", lambda **kwargs: calls.append(kwargs))

    main.main()

    assert calls == [
        {
            "table_name": "catalog.schema.table",
            "output_path": "s3://bucket/path",
            "file_format": "json",
            "where_clause": "",
        }
    ]


@pytest.mark.parametrize(
    "path",
    [
        "s3://bucket/path",
        "dbfs:/tmp/table-exporter/output",
        "/dbfs/tmp/table-exporter/output",
    ],
)
def test_validate_output_path_accepts_supported_locations(
    path: str, table_exporter_modules
) -> None:
    _main, validator = table_exporter_modules

    assert validator.validate_output_path(path) == path


@pytest.mark.parametrize(
    "table_name",
    [
        "catalog.schema.table",
        "`catalog`.schema.table",
    ],
)
def test_validate_table_name_accepts_three_part_names(
    table_name: str, table_exporter_modules
) -> None:
    _main, validator = table_exporter_modules

    assert validator.validate_table_name(table_name) == table_name


@pytest.mark.parametrize(
    "table_name",
    [
        "schema.table",
        "catalog.schema.table; DROP TABLE catalog.schema.table",
        "catalog.schema.table name",
    ],
)
def test_validate_table_name_rejects_invalid_names(
    table_name: str, table_exporter_modules
) -> None:
    _main, validator = table_exporter_modules

    with pytest.raises(ValueError):
        validator.validate_table_name(table_name)
