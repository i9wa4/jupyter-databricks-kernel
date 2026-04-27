# Examples

This directory contains sample projects using jupyter-databricks-kernel.

## table-exporter

Basic project structure for exporting Databricks tables to S3.

**Features:**

- Skinny notebook wrapper (3 cells)
- Pure Python business logic
- Code quality with Ruff/mypy
- Local development → Databricks Job execution

See: [table-exporter/README.md](./table-exporter/README.md)

## Usage

1. Copy the sample:

   ```bash
   cp -r examples/table-exporter my-project
   cd my-project
   ```

2. Set parameters:

   ```bash
   export TABLE_NAME='`catalog`.schema.table'
   export OUTPUT_PATH='s3://bucket/path/'
   ```

3. Run:

   ```bash
   jupyter lab launcher.ipynb
   ```
