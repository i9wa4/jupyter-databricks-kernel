# jupyter-databricks-kernel

[![PyPI version](https://badge.fury.io/py/jupyter-databricks-kernel.svg)](https://badge.fury.io/py/jupyter-databricks-kernel)
[![CI](https://github.com/i9wa4/jupyter-databricks-kernel/actions/workflows/ci.yaml/badge.svg)](https://github.com/i9wa4/jupyter-databricks-kernel/actions/workflows/ci.yaml)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python](https://img.shields.io/pypi/pyversions/jupyter-databricks-kernel.svg)](https://pypi.org/project/jupyter-databricks-kernel/)

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/i9wa4/jupyter-databricks-kernel)

A Jupyter kernel for complete remote execution on Databricks clusters.

## 1. Features

- Execute Python code entirely on Databricks clusters
  - Works with VS Code, JupyterLab, and other Jupyter frontends
  - CLI execution support with `jupyter execute` command
- Automatic file synchronization to the Databricks cluster driver node
  - Syncs your local project files to the cluster driver node before each
    execution
  - Respects `.gitignore` patterns and configurable exclude rules
  - Configurable size limits to prevent syncing large files

## 2. Requirements

- Python 3.11 or later
- Databricks workspace with authentication configured (supports Personal Access
  Token, OAuth M2M with Service Principal, etc.)
- Classic all-purpose cluster

## 3. Quick Start

1. Install the kernel:

   ```bash
   uv add jupyter-databricks-kernel
   uv run python -m jupyter_databricks_kernel.install
   ```

   Install options:

   | Option | Description |
   | --- | --- |
   | (default) | Install to current venv (`sys.prefix`) |
   | `--user` | Install to user site (`~/.local/share/jupyter/kernels/`) |
   | `--prefix PATH` | Install to custom path |

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

   # Service Principal authentication (alternative to PAT)
   export DATABRICKS_CLIENT_ID=your-client-id
   export DATABRICKS_CLIENT_SECRET=your-client-secret

   # Use specific profile from ~/.databrickscfg (optional)
   export DATABRICKS_CONFIG_PROFILE=your-profile-name
   ```

   For authentication options, see [Databricks SDK Authentication][sdk-auth].

3. Open a notebook and select "Databricks" kernel:

   **VS Code:**

   1. Install the [Jupyter extension][vscode-jupyter]
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

## Examples

See [examples/](./examples/) for sample projects:

- [table-exporter](./examples/table-exporter/) — Skinny notebook wrapper with
  pure Python business logic for exporting an existing Databricks table.

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

| Option                          | Description                            | Default       |
| ------------------------------- | -------------------------------------- | ------------- |
| `sync.enabled`                  | Enable file synchronization            | `true`        |
| `sync.source`                   | Source directory to sync               | `"."`         |
| `sync.exclude`                  | Additional exclude patterns            | `[]`          |
| `sync.max_size_mb`              | Maximum total project size in MB       | No limit      |
| `sync.max_file_size_mb`         | Maximum individual file size in MB     | No limit      |
| `sync.use_gitignore`            | Respect .gitignore patterns            | `true`        |
| `sync.workspace_extract_dir`    | Custom extraction directory on cluster | `null` (auto) |

The extraction directory can also be set via the
`JUPYTER_DATABRICKS_KERNEL_EXTRACT_DIR` environment variable, which takes
priority over `pyproject.toml`.

By default, files are extracted to
`/tmp/jupyter_databricks_kernel/<project>-<hash>/` on the cluster driver node,
where `<project>` is derived from the local project root directory name and
`<hash>` is derived from the project root path. This single path works
uniformly for user accounts and service principals while avoiding collisions
between different projects with the same directory name.

[sdk-auth]: https://docs.databricks.com/en/dev-tools/sdk-python.html#authentication
[vscode-jupyter]: https://marketplace.visualstudio.com/items?itemName=ms-toolsai.jupyter

## 5. CLI Execution

You can execute notebooks from the command line using `jupyter execute`:

```bash
jupyter execute notebook.ipynb --kernel_name=databricks --inplace
```

To save the output to a different file:

```bash
jupyter execute notebook.ipynb --kernel_name=databricks --output=output.ipynb
```

### 5.1. Options

| Option              | Description                                       |
| ------------------- | ------------------------------------------------- |
| `--kernel_name`     | Kernel name (use `databricks`)                    |
| `--output`          | Output file name                                  |
| `--inplace`         | Overwrite input file with results                 |
| `--timeout`         | Cell execution timeout in seconds                 |
| `--startup_timeout` | Kernel startup timeout in seconds (default: 60)   |
| `--allow-errors`    | Continue execution even if a cell raises an error |

### 5.2. Notes

If the cluster is stopped, kernel startup may take 5-6 minutes. Increase
`--startup_timeout` to avoid timeout errors:

```bash
jupyter execute notebook.ipynb --kernel_name=databricks --startup_timeout=600
```

### 5.3. Runner CLI (`run-py`, `run-db-py`, `run-ipynb`)

Execute scripts and notebooks directly without launching Jupyter:

```bash
uv run run-py path/to/script.py
uv run run-db-py path/to/notebook.py
uv run run-ipynb path/to/notebook.ipynb
```

Output is written to `.cache/outputs/<stem>.<YYYYMMDDTHHMMSS>.output.md`
relative to the current working directory. Use `--output-dir` to override the
directory.

#### Behavior notes

| Behavior | Details |
| --- | --- |
| Default output dir | `.cache/outputs/` (override with `--output-dir DIR`) |
| Output filename | `<stem>.<YYYYMMDDTHHMMSS>.output.md` — timestamped, never overwritten |
| Default timeout | 10 minutes per command/cell |
| Timeout handling | Cluster command is cancelled; error written to output file |
| Exit code | Exits with code 1 on error or timeout; code 0 on success |
| `run-ipynb --inplace` | Writes cell outputs back into the notebook; backup at `<path>.bak` |

## 6. Papermill Integration

[papermill](https://papermill.readthedocs.io/) supports parameter injection for
notebook pipelines. Use it with this kernel for parameterized remote execution
on Databricks clusters.

Install papermill:

```bash
uv add papermill
```

Run a notebook with parameter injection:

```bash
papermill input.ipynb output.ipynb --kernel databricks \
  -p param1 value1 -p param2 value2
```

Do NOT use the `--inplace` flag with papermill. Papermill is designed to
produce a new output notebook with injected parameters and captured cell
outputs; `--inplace` overwrites the source notebook and defeats this purpose.

If the cluster is stopped, increase the startup timeout:

```bash
papermill input.ipynb output.ipynb --kernel databricks \
  --start_timeout 600 -p param1 value1
```

## 7. MCP Server Usage Pattern

`jupyter-databricks-kernel` can be used by an external MCP (Model Context
Protocol) server as its Databricks execution dependency. This repository does
not ship an MCP server, Databricks App, HTTP adapter, or MCP tool definition.

### 7.1. External Server Responsibilities

A companion MCP server can be deployed once per Databricks workspace. That
server owns:

- Workspace authentication and Service Principal credentials
- MCP transport and tool definitions
- HTTP routing, if the server exposes an HTTP adapter
- Session storage and timeout policy
- Any output file persistence outside the command result returned by this
  package

The server can import `DatabricksExecutor` from this package to run code on a
configured all-purpose cluster. It should keep one executor per active client
session when isolated command contexts are required.

### 7.2. Project Routing

If a companion server supports multiple workspaces, keep workspace routing in
the companion server configuration. A project-local routing file such as
`.databricks/config.json` can be used by that server, but it is external to this
package's public API.

Example external routing shape:

```json
{
  "mcp_profile": "<profile-name>",
  "cluster_id": "<cluster-id>"
}
```

In this pattern, `mcp_profile` maps to a named companion server entry in the AI
agent's global config. Avoid duplicating workspace identity in both
`mcp_profile` and `workspace_url`; choose one source of truth in the companion
server.

### 7.3. Execution Flow

1. The AI agent selects the companion MCP server for the target workspace.
2. The companion server maps the request to a Databricks cluster.
3. The companion server calls `DatabricksExecutor` from this package.
4. `DatabricksExecutor` executes code through the Databricks Command Execution
   API and returns the result.
5. The companion server or AI agent decides whether and where to persist the
   returned output.

## 8. Known Limitations

- Serverless compute is not supported (Command Execution API limitation)
- `input()` and interactive prompts do not work
- Interactive widgets (ipywidgets) are not supported

## 9. Troubleshooting

### 9.1. Kernel feels slow

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

## 10. Development

See [CONTRIBUTING.md](./CONTRIBUTING.md) for development setup and guidelines.

## 11. License

Apache License 2.0
