# jupyter-databricks-session-kernel

A Jupyter kernel for complete remote execution on Databricks clusters.

## 1. Features

- Execute Python code entirely on Databricks clusters
- No local Python execution (unlike Databricks Connect)
- Seamless integration with JupyterLab

## 2. Requirements

- Python 3.11 or later
- Databricks workspace with Personal Access Token
- mise (for tool version management)

## 3. Quick Start

1. Install mise

   ```bash
   curl https://mise.run | sh
   ```

2. Install tools and dependencies

   ```bash
   make install
   make sync
   ```

3. Configure Databricks credentials (see Authentication section below)

## 4. Authentication

This kernel uses the [Databricks SDK for Python](https://docs.databricks.com/en/dev-tools/sdk-python.html) for authentication. The SDK automatically resolves credentials in the following order:

1. Environment variables (`DATABRICKS_HOST`, `DATABRICKS_TOKEN`)
2. Databricks CLI configuration (`~/.databrickscfg`)
3. Azure CLI / Google Cloud authentication (if applicable)

### 4.1. Required Permissions

The authenticated user or service principal needs the following workspace permissions:

- **Cluster access**: "Can Attach To" or "Can Restart" permission on the target cluster
- **DBFS access**: Read/write access to `/tmp/` for file synchronization
- **Workspace access**: Read/write access to `/Workspace/Users/{your-email}/` for code extraction

Note: Databricks PATs inherit the permissions of the user who created them. For fine-grained access control, consider using [OAuth](https://docs.databricks.com/en/dev-tools/auth/oauth-m2m.html) or configure cluster access control lists.

### 4.2. Environment Variables

```bash
export DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
export DATABRICKS_TOKEN=your-personal-access-token
export DATABRICKS_CLUSTER_ID=your-cluster-id
```

### 4.3. Using Databricks CLI

If you have the Databricks CLI configured, the SDK will use `~/.databrickscfg`:

```bash
databricks configure --token
```

### 4.4. Configuration File

You can also set `cluster_id` in `.databricks-kernel.yaml`:

```yaml
cluster_id: "0123-456789-abcdef12"
```

For more authentication options including OAuth and SSO, see [Databricks SDK Authentication](https://docs.databricks.com/en/dev-tools/sdk-python.html#authentication).

## 5. File Synchronization

This kernel synchronizes local files to DBFS for execution on the remote cluster. The synchronization behavior matches the [Databricks CLI](https://docs.databricks.com/en/dev-tools/cli/index.html).

### 5.1. Excluded Files

- `.gitignore` patterns: All patterns in your `.gitignore` file are respected
- `.databricks` directory: Always excluded (matching Databricks CLI behavior)

### 5.2. Custom Exclusions

You can add additional exclusion patterns in `.databricks-kernel.yaml`:

```yaml
sync:
  exclude:
    - "*.log"
    - "data/"
```

### 5.3. Size Limits

You can configure file size limits to prevent syncing large files or projects:

| Option | Description | Default |
|--------|-------------|---------|
| `max_size_mb` | Maximum total project size in MB | No limit |
| `max_file_size_mb` | Maximum individual file size in MB | No limit |

Example configuration:

```yaml
sync:
  max_size_mb: 100.0
  max_file_size_mb: 10.0
```

If the size limit is exceeded, a `FileSizeError` is raised before syncing starts. The error message indicates which file or total size exceeded the limit, allowing you to adjust `exclude` patterns or increase the limit.

## 6. Documentation

For detailed documentation, see the [docs](./docs/) directory:

- [Architecture](./docs/architecture.md) - Design overview and data flow
- [Setup](./docs/setup.md) - Installation and configuration
- [Usage](./docs/usage.md) - How to use the kernel
- [Use Cases](./docs/use-cases.md) - Example scenarios and comparison
- [Constraints](./docs/constraints.md) - Limitations and best practices
- [Roadmap](./docs/roadmap.md) - Future plans

## 7. Development

### 7.1. Available Commands

| Command | Description |
|---------|-------------|
| `make install` | Install mise tools |
| `make sync` | Sync Python dependencies |
| `make test` | Run tests |
| `make jupyter` | Start JupyterLab |

### 7.2. Code Quality

```bash
mise exec -- pre-commit run --all-files
```

## 8. Databricks Runtime Compatibility

| Runtime | Python | Status |
|---------|--------|--------|
| 17.3 LTS | 3.12.3 | Recommended |
| 16.4 LTS | 3.12.3 | Recommended |
| 15.4 LTS | 3.11.11 | Supported |

## 9. License

Apache License 2.0
