# jupyter-databricks-kernel

[![PyPI version](https://badge.fury.io/py/jupyter-databricks-kernel.svg)](https://badge.fury.io/py/jupyter-databricks-kernel)
[![CI](https://github.com/i9wa4/jupyter-databricks-kernel/actions/workflows/ci.yaml/badge.svg)](https://github.com/i9wa4/jupyter-databricks-kernel/actions/workflows/ci.yaml)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python](https://img.shields.io/pypi/pyversions/jupyter-databricks-kernel.svg)](https://pypi.org/project/jupyter-databricks-kernel/)

A Jupyter kernel for complete remote execution on Databricks clusters.

## 1. Features

- Execute Python code entirely on Databricks clusters
- Seamless integration with JupyterLab

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
   # Required: cluster ID (or set in pyproject.toml)
   export DATABRICKS_CLUSTER_ID=your-cluster-id

   # Authentication: choose one of the following
   # Option A: Environment variables
   export DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
   export DATABRICKS_TOKEN=your-personal-access-token

   # Option B: Use ~/.databrickscfg (DEFAULT profile)
   # Option C: Use specific profile from ~/.databrickscfg
   export DATABRICKS_CONFIG_PROFILE=your-profile-name
   ```

   For authentication options, see [Databricks SDK Authentication][sdk-auth].

3. Start JupyterLab and select "Databricks" kernel:

   ```bash
   jupyter-lab
   ```

4. Run a simple test:

   ```python
   print("Hello from Databricks!")
   spark.version
   ```

If the cluster is stopped, the first execution may take 5-6 minutes while
the cluster starts.

## 4. Configuration

You can configure the kernel in `pyproject.toml`:

```toml
[tool.jupyter-databricks-kernel]
cluster_id = "0123-456789-abcdef12"

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
| `cluster_id`            | Target cluster ID                  | Required |
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

## 6. Development

See [CONTRIBUTING.md](./CONTRIBUTING.md) for development setup and guidelines.

## 7. License

Apache License 2.0
