# table-exporter

Example project demonstrating the Skinny Notebook Wrapper + Pure Python pattern
with `jupyter-databricks-kernel`.

## Project Structure

```text
table-exporter/
├── .ruff.toml           # Ruff configuration
├── pyproject.toml       # Project metadata and tool config
├── launcher.ipynb       # Skinny wrapper (3 cells only)
├── main.py              # Entry point
├── common/
│   ├── __init__.py
│   ├── params.py        # Parameter handling utilities
│   └── validator.py     # Validation utilities
└── processors/
    ├── __init__.py
    └── exporter.py      # Business logic (uses Spark)
```

## How the Notebook Works

`launcher.ipynb` has exactly 3 cells:

1. **Widget definitions** — `dbutils.widgets.text()` calls that declare each
   parameter with a default. Databricks Jobs override these via
   `base_parameters` at runtime; locally you can fill them in the widget UI.
2. **Widget reads** — assigns Python variables from `dbutils.widgets.get()`.
3. **Execute** — calls `main.main(table_name=..., output_path=...,
   file_format=..., where_clause=...)`.

## Development

```bash
# Launch Jupyter with Databricks kernel and fill widget values interactively
jupyter lab launcher.ipynb
```

## Running as a Databricks Job

Configure the notebook task to point at `launcher` with base parameters.
Each key maps to the widget name defined in cell 1:

```json
{
  "notebook_task": {
    "notebook_path": "/Workspace/project/launcher",
    "base_parameters": {
      "table_name": "`catalog`.schema.table",
      "output_path": "s3://bucket/path/",
      "file_format": "parquet",
      "where_clause": ""
    }
  }
}
```
