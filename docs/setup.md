# Setup

## 1. Prerequisites

- Python 3.11 or later
- [mise](https://mise.jdx.dev/) for tool version management
- Databricks workspace with access to a cluster

## 2. Installation

### 2.1. Install mise

```bash
curl https://mise.run | sh
```

### 2.2. Install Tools and Dependencies

```bash
# Install mise-managed tools
make install

# Sync Python dependencies
make sync
```

## 3. Databricks Configuration

### 3.1. Cluster Requirements

This kernel requires a classic all-purpose cluster. The following cluster types are supported:

| Cluster Type | Supported |
|--------------|-----------|
| All-purpose (classic) | Yes |
| Job cluster | No |
| Serverless | No (API limitation) |

Serverless clusters are not supported because the Command Execution API, which this kernel relies on, is not available for serverless compute.

### 3.2. Required Permissions

The authenticated user or service principal needs:

| Permission | Resource | Purpose |
|------------|----------|---------|
| Can Attach To | Target cluster | Execute code on the cluster |
| Read/Write | DBFS `/tmp/` | Store synchronized files |
| Read/Write | Workspace `/Users/{your-email}/` | Extract files for execution |

## 4. Authentication

This kernel uses the [Databricks SDK for Python](https://docs.databricks.com/en/dev-tools/sdk-python.html), which supports multiple authentication methods.

### 4.1. Authentication Precedence

The SDK resolves credentials in this order:

1. Environment variables
2. Databricks CLI configuration (`~/.databrickscfg`)
3. Azure CLI authentication (for Azure Databricks)
4. Google Cloud authentication (for GCP Databricks)

### 4.2. Option 1: Environment Variables (Recommended for CI/CD)

Set the following environment variables:

```bash
export DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
export DATABRICKS_TOKEN=your-personal-access-token
export DATABRICKS_CLUSTER_ID=your-cluster-id
```

### 4.3. Option 2: Databricks CLI Configuration

If you have the Databricks CLI installed, configure it:

```bash
databricks configure --token
```

This creates `~/.databrickscfg` with your credentials. Then set only the cluster ID:

```bash
export DATABRICKS_CLUSTER_ID=your-cluster-id
```

Or use `.jupyter-databricks-kernel.yaml`:

```yaml
cluster_id: "your-cluster-id"
```

### 4.4. Option 3: Configuration File

Create `.jupyter-databricks-kernel.yaml` in your project root:

```yaml
cluster_id: "0123-456789-abcdef12"
```

The kernel will use Databricks CLI credentials for host and token.

### 4.5. Finding Your Cluster ID

1. Open your Databricks workspace
2. Navigate to Compute
3. Click on your cluster
4. The cluster ID is in the URL: `https://workspace.cloud.databricks.com/#/setting/clusters/{cluster-id}/configuration`

Or use the CLI:

```bash
databricks clusters list
```

## 5. Verification

After setup, verify your configuration:

```bash
# Start JupyterLab
make jupyter
```

1. Select "Databricks Session" kernel
2. Run a simple test:

```python
print("Hello from Databricks!")
spark.version
```

If the cluster is stopped, the first execution may take 5-6 minutes while the cluster starts.

## 6. Troubleshooting

### 6.1. "DATABRICKS_CLUSTER_ID environment variable is not set"

Set the cluster ID via environment variable or `.jupyter-databricks-kernel.yaml`.

### 6.2. "Authentication error" or "Invalid token"

1. Verify your token is valid: `databricks auth token`
2. Check token expiration
3. Regenerate token if needed

### 6.3. "Cluster not found"

1. Verify the cluster ID is correct
2. Ensure you have permission to access the cluster
3. Check if the cluster has been terminated

### 6.4. Long First Execution Time

The first execution may take 5-6 minutes if the cluster is stopped. This is expected behavior as Databricks starts the cluster.
