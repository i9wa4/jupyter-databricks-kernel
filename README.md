# jupyter-databricks-kernel

[![PyPI version](https://badge.fury.io/py/jupyter-databricks-kernel.svg)](https://badge.fury.io/py/jupyter-databricks-kernel)
[![CI](https://github.com/i9wa4/jupyter-databricks-kernel/actions/workflows/ci.yaml/badge.svg)](https://github.com/i9wa4/jupyter-databricks-kernel/actions/workflows/ci.yaml)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python](https://img.shields.io/pypi/pyversions/jupyter-databricks-kernel.svg)](https://pypi.org/project/jupyter-databricks-kernel/)

A Jupyter kernel for complete remote execution on Databricks clusters.

## 1. Features

- Execute Python code entirely on Databricks clusters
- No local Python execution (unlike Databricks Connect)
- Seamless integration with JupyterLab

## 2. Requirements

- Python 3.11 or later
- Databricks workspace with Personal Access Token
- Classic all-purpose cluster (serverless compute is not supported)

### 2.1. Why Serverless is Not Supported

This kernel uses the [Command Execution API][cmd-api], which only works with
classic all-purpose clusters. Serverless compute uses a different architecture
(Spark Connect) and does not provide an API for interactive Python code
execution.

[cmd-api]: https://docs.databricks.com/api/workspace/commandexecution

For serverless compute, consider using [Databricks Connect][db-connect]
instead.

[db-connect]: https://docs.databricks.com/dev-tools/databricks-connect/

## 3. Installation

```bash
pip install jupyter-databricks-kernel
python -m jupyter_databricks_kernel.install
```

## 4. Configuration

### 4.1. Environment Variables

```bash
export DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
export DATABRICKS_TOKEN=your-personal-access-token
export DATABRICKS_CLUSTER_ID=your-cluster-id
```

### 4.2. Using Databricks CLI

If you have the Databricks CLI configured, the SDK will use `~/.databrickscfg`:

```bash
databricks configure --token
```

### 4.3. Configuration File

You can configure the kernel in `pyproject.toml`:

```toml
[tool.jupyter-databricks-kernel]
cluster_id = "0123-456789-abcdef12"
```

For more authentication options including OAuth and SSO, see
[Databricks SDK Authentication][sdk-auth].

[sdk-auth]: https://docs.databricks.com/en/dev-tools/sdk-python.html#authentication

### 4.4. Required Permissions

The authenticated user or service principal needs the following workspace
permissions:

- Cluster access: "Can Attach To" or "Can Restart" permission on the target
  cluster
- DBFS access: Read/write access to `/tmp/` for file synchronization
- Workspace access: Read/write access to `/Workspace/Users/{your-email}/` for
  code extraction

Note: Databricks PATs inherit the permissions of the user who created them.
For fine-grained access control, consider using [OAuth][oauth-m2m] or
configure cluster access control lists.

[oauth-m2m]: https://docs.databricks.com/en/dev-tools/auth/oauth-m2m.html

## 5. Quick Start

1. Start JupyterLab:

   ```bash
   jupyter lab
   ```

2. Select "Databricks Session" kernel

3. Run a simple test:

   ```python
   print("Hello from Databricks!")
   spark.version
   ```

If the cluster is stopped, the first execution may take 5-6 minutes while
the cluster starts.

## 6. File Synchronization

This kernel synchronizes local files to DBFS for execution on the remote
cluster.

### 6.1. Default Exclusions

The `.databricks` directory is always excluded (matching Databricks CLI
behavior).

### 6.2. .gitignore Patterns

By default, all patterns in your `.gitignore` file are respected (matching
Databricks CLI behavior).

You can disable this behavior if needed:

```toml
[tool.jupyter-databricks-kernel.sync]
use_gitignore = false
```

### 6.3. Custom Exclusions

You can add additional exclusion patterns:

```toml
[tool.jupyter-databricks-kernel.sync]
exclude = ["*.log", "data/"]
```

### 6.4. Size Limits

You can configure file size limits to prevent syncing large files or projects:

| Option             | Description                        | Default   |
| --------           | -------------                      | --------- |
| `max_size_mb`      | Maximum total project size in MB   | No limit  |
| `max_file_size_mb` | Maximum individual file size in MB | No limit  |

Example configuration:

```toml
[tool.jupyter-databricks-kernel.sync]
max_size_mb = 100.0
max_file_size_mb = 10.0
```

If the size limit is exceeded, a `FileSizeError` is raised before syncing
starts. The error message indicates which file or total size exceeded the
limit, allowing you to adjust `exclude` patterns or increase the limit.

### 6.5. Full Configuration Example

```toml
[tool.jupyter-databricks-kernel]
cluster_id = "0123-456789-abcdef12"

[tool.jupyter-databricks-kernel.sync]
enabled = true
source = "."
exclude = ["*.log", "data/", "*.tmp"]
max_size_mb = 100.0
max_file_size_mb = 10.0
use_gitignore = true
```

## 7. Troubleshooting

### 7.1. Authentication Errors

| Error                                 | Solution                                                                |
| -------                               | ----------                                                              |
| `DATABRICKS_HOST not set`             | Set `DATABRICKS_HOST` environment variable                              |
| `DATABRICKS_TOKEN not set`            | Set `DATABRICKS_TOKEN` environment variable or configure Databricks CLI |
| `Invalid token` or `401 Unauthorized` | Regenerate your Personal Access Token                                   |

### 7.2. Cluster Errors

| Error                           | Solution                                                   |
| -------                         | ----------                                                 |
| `DATABRICKS_CLUSTER_ID not set` | Set `DATABRICKS_CLUSTER_ID` or configure in pyproject.toml |
| `Cluster not found`             | Verify cluster ID and your access permissions              |
| `Cluster terminated`            | Restart the cluster from Databricks workspace              |

### 7.3. Sync Errors

| Error                           | Solution                                            |
| -------                         | ----------                                          |
| `FileSizeError: exceeded limit` | Adjust `exclude` patterns or increase `max_size_mb` |
| `Permission denied on DBFS`     | Verify DBFS write access to `/tmp/`                 |
| `Socket file skipped`           | Expected behavior; socket files cannot be synced    |

### 7.4. Kernel Errors

| Error                               | Solution                                               |
| -------                             | ----------                                             |
| Kernel not found after installation | Run `python -m jupyter_databricks_kernel.install`      |
| Context timeout                     | Cluster may have restarted; re-run your cells          |
| Connection lost                     | Check network connectivity; kernel will auto-reconnect |

For more detailed troubleshooting, see [docs/setup.md](./docs/setup.md#6-troubleshooting).

## 8. Databricks Runtime Compatibility

| Runtime                                                                      | Python   | Status      |
| ---------                                                                    | -------- | --------    |
| [17.3 LTS](https://docs.databricks.com/aws/en/release-notes/runtime/17.3lts) | 3.12.3   | Recommended |
| [16.4 LTS](https://docs.databricks.com/aws/en/release-notes/runtime/16.4lts) | 3.12.3   | Recommended |
| [15.4 LTS](https://docs.databricks.com/aws/en/release-notes/runtime/15.4lts) | 3.11.11  | Supported   |

For all supported runtimes, see [Databricks Runtime release notes](https://docs.databricks.com/aws/en/release-notes/runtime/).

## 9. Documentation

For detailed documentation, see the [docs](./docs/) directory:

- [Architecture](./docs/architecture.md) - Design overview and data flow
- [Setup](./docs/setup.md) - Installation and configuration
- [Usage](./docs/usage.md) - How to use the kernel
- [Use Cases](./docs/use-cases.md) - Example scenarios and comparison
- [Constraints](./docs/constraints.md) - Limitations and best practices
- [Roadmap](./docs/roadmap.md) - Future plans

## 10. Development

See [CONTRIBUTING.md](./CONTRIBUTING.md) for development setup and guidelines.

## 11. Changelog

See [Releases](https://github.com/i9wa4/jupyter-databricks-kernel/releases)

## 12. License

Apache License 2.0
