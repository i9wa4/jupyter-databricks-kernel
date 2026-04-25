# table-exporter

Example project demonstrating the Skinny Notebook Wrapper + Pure Python pattern
with `jupyter-databricks-kernel`.

## Project Structure

```
table-exporter/
├── .ruff.toml           # Ruff configuration
├── launcher.ipynb       # Skinny wrapper (3 cells only)
├── main.py              # Entry point
├── common/
│   ├── __init__.py
│   ├── params.py        # Parameter handling
│   └── validator.py     # Validation utilities
└── processors/
    ├── __init__.py
    └── exporter.py      # Business logic (uses dbutils/Spark)
```

## Development

```bash
# Set parameters via environment variables
export TABLE_NAME='`catalog`.schema.table'
export OUTPUT_PATH='s3://bucket/path/'
export FILE_FORMAT='json'

# Launch Jupyter with Databricks kernel
jupyter lab launcher.ipynb
```

## Running as a Databricks Job

Configure the notebook task to point at `launcher` with base parameters:

```json
{
  "notebook_task": {
    "notebook_path": "/Workspace/project/launcher",
    "base_parameters": {
      "table_name": "`catalog`.schema.table",
      "output_path": "s3://bucket/path/",
      "file_format": "json"
    }
  }
}
```
