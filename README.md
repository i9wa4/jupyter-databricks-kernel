# jupyter-databricks-kernel

[![PyPI version](https://badge.fury.io/py/jupyter-databricks-kernel.svg)](https://badge.fury.io/py/jupyter-databricks-kernel)
[![CI](https://github.com/i9wa4/jupyter-databricks-kernel/actions/workflows/ci.yaml/badge.svg)](https://github.com/i9wa4/jupyter-databricks-kernel/actions/workflows/ci.yaml)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python](https://img.shields.io/pypi/pyversions/jupyter-databricks-kernel.svg)](https://pypi.org/project/jupyter-databricks-kernel/)

A Jupyter kernel for complete remote execution on Databricks clusters.

## 1. Features

- Execute Python code entirely on Databricks clusters
- Works with VS Code, JupyterLab, and other Jupyter frontends

## 2. Requirements

- Python 3.11 or later
- Databricks workspace with Personal Access Token
- Classic all-purpose cluster

## 3. Quick Start

1. Install the kernel:

   ```bash
   # With uv
   uv pip install jupyter-databricks-kernel
   uv run python -m jupyter_databricks_kernel.install

   # With pip
   pip install jupyter-databricks-kernel
   python -m jupyter_databricks_kernel.install
   ```

   Install options:

   | Option          | Description                                                   |
   | ------          | -----------                                                   |
   | (default)       | Install to current venv (`sys.prefix`)                        |
   | `--user`        | Install to user directory (`~/.local/share/jupyter/kernels/`) |
   | `--prefix PATH` | Install to custom path                                        |

2. Configure authentication and cluster:

   ```bash
   # Recommended: Use Databricks CLI to set up everything
   databricks auth login --configure-cluster
   ```

   This creates `~/.databrickscfg` with authentication credentials and
   cluster ID.

   Alternatively, use environment variables:

   ```bash
   # Override cluster ID (optional, takes priority over ~/.databrickscfg)
   export DATABRICKS_CLUSTER_ID=your-cluster-id

   # Authentication (if not using ~/.databrickscfg)
   export DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
   export DATABRICKS_TOKEN=your-personal-access-token

   # Use specific profile from ~/.databrickscfg (optional)
   export DATABRICKS_CONFIG_PROFILE=your-profile-name
   ```

   For authentication options, see [Databricks SDK Authentication][sdk-auth].

3. Open a notebook and select "Databricks" kernel:

   **VS Code:**

   1. Install the [Jupyter extension](https://marketplace.visualstudio.com/items?itemName=ms-toolsai.jupyter)
   2. Open a `.ipynb` file
   3. Click "Select Kernel" and choose "Databricks"

   **JupyterLab:**

   ```bash
   jupyter-lab
   ```

   Select "Databricks" from the kernel list.

4. Run a simple test:

   ```python
   spark.version
   ```

If the cluster is stopped, the first execution may take 5-6 minutes while
the cluster starts.

## 4. Configuration

### 4.1. Cluster ID

Cluster ID is read from (in order of priority):

1. `DATABRICKS_CLUSTER_ID` environment variable
2. `~/.databrickscfg` (from active profile)

Active profile is determined by `DATABRICKS_CONFIG_PROFILE` environment
variable, or `DEFAULT` if not set.

Example `~/.databrickscfg`:

```ini
[DEFAULT]
host = https://your-workspace.cloud.databricks.com
token = dapi...
cluster_id = 0123-456789-abcdef12
```

### 4.2. Sync Settings

You can configure file synchronization in `pyproject.toml`:

```toml
[tool.jupyter-databricks-kernel.sync]
enabled = true
source = "."
exclude = ["*.log", "data/"]
max_size_mb = 100.0
max_file_size_mb = 10.0
use_gitignore = true
```

| Option                  | Description                        | Default  |
| ------                  | -----------                        | -------  |
| `sync.enabled`          | Enable file synchronization        | `true`   |
| `sync.source`           | Source directory to sync           | `"."`    |
| `sync.exclude`          | Additional exclude patterns        | `[]`     |
| `sync.max_size_mb`      | Maximum total project size in MB   | No limit |
| `sync.max_file_size_mb` | Maximum individual file size in MB | No limit |
| `sync.use_gitignore`    | Respect .gitignore patterns        | `true`   |

[sdk-auth]: https://docs.databricks.com/en/dev-tools/sdk-python.html#authentication

## 5. Known Limitations

- Serverless compute is not supported (Command Execution API limitation)
- `input()` and interactive prompts do not work
- Interactive widgets (ipywidgets) are not supported

## 6. Troubleshooting

### 6.1. Kernel feels slow

File sync may be uploading unnecessary files. Check your sync settings:

1. Ensure `.gitignore` includes large/unnecessary files:

   ```text
   .venv/
   __pycache__/
   *.pyc
   data/
   *.parquet
   node_modules/
   ```

2. Add exclude patterns in `pyproject.toml`:

   ```toml
   [tool.jupyter-databricks-kernel.sync]
   exclude = ["data/", "models/", "*.csv"]
   ```

3. Set size limits to catch unexpected large files:

   ```toml
   [tool.jupyter-databricks-kernel.sync]
   max_size_mb = 50.0
   max_file_size_mb = 10.0
   ```

4. Disable sync entirely if not needed:

   ```toml
   [tool.jupyter-databricks-kernel.sync]
   enabled = false
   ```

## 7. Development

See [CONTRIBUTING.md](./CONTRIBUTING.md) for development setup and guidelines.

## 8. License

Apache License 2.0
