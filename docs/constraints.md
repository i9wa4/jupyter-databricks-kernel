# Constraints

## 1. Cluster Requirements

### 1.1. Supported Cluster Types

| Cluster Type | Supported | Notes |
|--------------|-----------|-------|
| All-purpose (classic) | Yes | Recommended |
| Job cluster | No | No interactive API |
| Serverless | No | Command Execution API not available |

### 1.2. Why Serverless is Not Supported

This kernel uses the [Command Execution API](https://docs.databricks.com/api/workspace/commandexecution) to run code on Databricks clusters. This API is not available for serverless compute, which uses a different execution model.

## 2. Performance Considerations

### 2.1. Cluster Startup Time

If the target cluster is stopped, the first code execution will wait for the cluster to start:

| Cluster Size | Typical Startup Time |
|--------------|---------------------|
| Small (1-2 nodes) | 3-5 minutes |
| Medium (3-10 nodes) | 5-7 minutes |
| Large (10+ nodes) | 7-10 minutes |

To minimize wait time:

- Keep frequently-used clusters running
- Use cluster policies with auto-start
- Consider warm pools for faster startup

### 2.2. File Synchronization

Initial sync may take time depending on project size:

| Project Size | Sync Time |
|--------------|-----------|
| Small (< 10 MB) | < 5 seconds |
| Medium (10-100 MB) | 5-30 seconds |
| Large (100+ MB) | 30+ seconds |

Subsequent syncs are faster due to hash-based change detection.

### 2.3. Execution Latency

Each code execution involves network round-trips:

- Local to Databricks: ~100-500ms
- Cluster execution: varies
- Results return: ~100-500ms

For interactive development, this latency is typically acceptable. For tight loops, batch operations locally before sending to the cluster.

## 3. File Size Limits

### 3.1. Configurable Limits

Set limits in `.databricks-kernel.yaml`:

```yaml
sync:
  # Maximum size for a single file (MB)
  max_file_size_mb: 100.0

  # Maximum total size for all synced files (MB)
  max_size_mb: 1000.0
```

### 3.2. DBFS Limits

DBFS has its own limits:

| Limit | Value |
|-------|-------|
| Maximum file size | 2 GB |
| Maximum PUT request | 1 MB (chunked upload for larger) |

The kernel handles chunked uploads automatically, but very large files may cause timeouts.

### 3.3. Recommendations

- Exclude large data files from sync
- Use DBFS or cloud storage for datasets
- Keep synchronized code under 100 MB

## 4. State Behavior

### 4.1. Variable Persistence

Variables persist within a session but are lost on:

- Cluster restart
- Context invalidation (idle timeout)
- Kernel shutdown

```python
# This variable persists during the session
my_data = spark.read.parquet("/data/")

# After cluster restart, my_data is undefined
# You must re-run the cell
```

### 4.2. No State Serialization

Unlike some notebook environments, this kernel does not serialize state:

- No checkpoint/restore functionality
- No session persistence across restarts
- All variables must be recreated after restart

### 4.3. Reconnection Behavior

When the kernel reconnects (e.g., after context timeout):

1. Execution context is recreated
2. Files are re-synchronized
3. All variables are lost
4. You must re-run previous cells

## 5. Exclude Patterns Best Practices

### 5.1. Recommended Excludes

```yaml
sync:
  exclude:
    # Data files
    - "data/"
    - "*.csv"
    - "*.parquet"
    - "*.json"

    # Large artifacts
    - "models/"
    - "*.pkl"
    - "*.h5"

    # Build artifacts
    - "__pycache__/"
    - "*.pyc"
    - "*.egg-info/"
    - "dist/"
    - "build/"

    # Virtual environments
    - ".venv/"
    - "venv/"

    # IDE files
    - ".idea/"
    - ".vscode/"

    # Notebooks (if using Databricks notebooks)
    - "*.ipynb"

    # Logs
    - "*.log"
    - "logs/"
```

### 5.2. Pattern Syntax

Patterns follow gitignore syntax:

| Pattern | Matches |
|---------|---------|
| `*.log` | All .log files |
| `data/` | data directory and contents |
| `**/temp` | temp directory at any level |
| `!important.log` | Exclude from ignore (negate) |

### 5.3. Combining with .gitignore

The kernel automatically respects your `.gitignore` file. Additional patterns in `.databricks-kernel.yaml` are combined with gitignore patterns.

## 6. Security Considerations

### 6.1. Credentials

- Never commit `.databricks-kernel.yaml` with credentials
- Use environment variables for CI/CD
- Tokens inherit user permissions

### 6.2. File Synchronization

- Files are uploaded to your DBFS space
- Files are extracted to your Workspace directory
- Other users with workspace access may see synced files
- Clean up occurs on kernel shutdown

### 6.3. Recommended .gitignore

```gitignore
# Kernel configuration (may contain cluster ID)
.databricks-kernel.yaml

# Cache file
.databricks-kernel-cache.json

# Databricks directory
.databricks/
```

## 7. Known Limitations

### 7.1. No Interactive Input

`input()` and similar interactive prompts do not work:

```python
# This will hang
name = input("Enter name: ")  # Don't use this
```

### 7.2. Display Limitations

Some rich display types may not render correctly:

- Interactive widgets (ipywidgets)
- Some matplotlib backends
- Real-time streaming output

### 7.3. Concurrent Execution

Only one cell can execute at a time per kernel instance. Concurrent execution requires multiple notebooks/kernels.

## 8. Timeouts

### 8.1. Default Timeouts

| Operation | Timeout |
|-----------|---------|
| Context creation | 5 minutes |
| Command execution | 10 minutes |
| Reconnection delay | 1 second |

These timeouts are not currently configurable. Long-running operations may fail. For very long operations, consider using Databricks Jobs instead.
