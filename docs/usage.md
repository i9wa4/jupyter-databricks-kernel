# Usage

## 1. Quick Start

### 1.1. Starting JupyterLab

```bash
make jupyter
```

This starts JupyterLab with the Databricks Session kernel available.

### 1.2. Selecting the Kernel

1. Open or create a notebook
2. Click on the kernel selector (top right)
3. Select "Databricks Session"

### 1.3. Basic Execution

```python
# All code runs on the remote Databricks cluster
print("Hello from Databricks!")

# Spark is available
df = spark.range(10)
df.show()

# dbutils is available
dbutils.fs.ls("/")
```

## 2. Configuration Reference

### 2.1. Configuration File

Create `.jupyter-databricks-kernel.yaml` in your project root:

```yaml
# Required: Databricks cluster ID
# Can also be set via DATABRICKS_CLUSTER_ID environment variable
cluster_id: "0123-456789-abcdef12"

# File synchronization settings
sync:
  # Enable/disable file sync (default: true)
  enabled: true

  # Source directory to sync (default: ".")
  source: "."

  # Additional exclude patterns (added to .gitignore patterns)
  exclude:
    - "*.log"
    - "data/"
    - "*.csv"
    - "__pycache__"

  # Maximum single file size in MB (default: no limit)
  max_file_size_mb: 100.0

  # Maximum total sync size in MB (default: no limit)
  max_size_mb: 1000.0
```

### 2.2. Environment Variables

| Variable | Description | Priority |
|----------|-------------|----------|
| `DATABRICKS_CLUSTER_ID` | Target cluster ID | Highest |
| `DATABRICKS_HOST` | Workspace URL | Used by SDK |
| `DATABRICKS_TOKEN` | Personal Access Token | Used by SDK |

Environment variables take precedence over configuration file values.

### 2.3. Configuration Precedence

For cluster_id:

1. `DATABRICKS_CLUSTER_ID` environment variable
2. `cluster_id` in `.jupyter-databricks-kernel.yaml`

For authentication (handled by Databricks SDK):

1. Environment variables (`DATABRICKS_HOST`, `DATABRICKS_TOKEN`)
2. Databricks CLI configuration (`~/.databrickscfg`)
3. Cloud provider authentication

## 3. File Synchronization

### 3.1. How It Works

The kernel automatically synchronizes your local project files to the Databricks cluster:

1. On each code execution, the kernel checks for file changes
2. Changed files are uploaded to DBFS
3. Files are extracted to your Workspace directory
4. The directory is added to Python's `sys.path`

This allows you to import local modules in your notebooks:

```python
# Local file: ./src/my_module.py
from src.my_module import MyClass
```

### 3.2. Exclude Patterns

Files are excluded from synchronization based on:

1. `.databricks` directory (always excluded, matching Databricks CLI)
2. Patterns in your `.gitignore` file
3. Patterns in `.jupyter-databricks-kernel.yaml` `sync.exclude`

Example `.gitignore`:

```gitignore
# These patterns are automatically respected
__pycache__/
*.pyc
.venv/
*.egg-info/
```

Example additional exclusions in `.jupyter-databricks-kernel.yaml`:

```yaml
sync:
  exclude:
    - "data/"
    - "*.log"
    - "notebooks/"
    - "tests/"
```

### 3.3. Cache Behavior

The kernel maintains a hash cache (`.jupyter-databricks-kernel-cache.json`) to detect file changes efficiently:

- Only changed files trigger a new sync
- Cache is stored locally in your project directory
- Delete the cache file to force a full resync

## 4. Working with Spark

### 4.1. SparkSession

A pre-configured SparkSession is available as `spark`:

```python
# Read data
df = spark.read.parquet("/path/to/data")

# SQL queries
spark.sql("SELECT * FROM my_table").show()

# Create tables
df.write.saveAsTable("my_new_table")
```

### 4.2. dbutils

The `dbutils` object is available for Databricks utilities:

```python
# File system operations
dbutils.fs.ls("/")
dbutils.fs.head("/path/to/file")

# Secrets
dbutils.secrets.get(scope="my-scope", key="my-key")

# Widgets
dbutils.widgets.text("param", "default")
value = dbutils.widgets.get("param")
```

## 5. Kernel Management

### 5.1. Restarting the Kernel

Restarting the kernel:

- Resets the initialization state
- Does NOT destroy the execution context
- Does NOT delete synchronized files

A full restart requires shutting down and starting a new kernel.

### 5.2. Shutting Down

When you close the notebook or shutdown the kernel:

- Execution context is destroyed
- DBFS files are cleaned up
- Workspace files are cleaned up

### 5.3. Reconnection

If the cluster restarts or the context becomes invalid:

- The kernel automatically detects the error
- Creates a new execution context
- Re-synchronizes files
- Retries the command

Note: Variables from previous executions are lost on reconnection.
