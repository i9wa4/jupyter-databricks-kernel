# Roadmap

## 1. Planned Features

### 1.1. Differential Sync (rsync-style)

Currently, the kernel uploads all files as a ZIP archive. A future improvement would sync only changed files incrementally:

- Reduce sync time for large projects
- Lower bandwidth usage
- Faster iteration cycles

### 1.2. Improved Error Messages

Enhance error reporting with:

- Clearer authentication error messages
- Better context for cluster errors
- Suggestions for common issues

### 1.3. Configurable Timeouts

Allow users to configure:

- Context creation timeout
- Command execution timeout
- Reconnection delay

### 1.4. Progress Indicators

Show progress for:

- File synchronization
- Cluster startup
- Long-running operations

## 2. Under Consideration

### 2.1. Multiple Cluster Support

Ability to switch between clusters within a session:

```yaml
clusters:
  default: "cluster-1"
  gpu: "gpu-cluster"
  large: "high-memory-cluster"
```

### 2.2. Serverless Support

Pending Databricks API support for Command Execution on serverless compute. Currently blocked by API limitations.

### 2.3. State Persistence

Optional serialization of session state:

- Checkpoint variables
- Restore on reconnection
- Reduce re-execution after cluster restart

### 2.4. Workspace Integration

Better integration with Databricks Workspace:

- Sync to Repos instead of user directory
- Git integration
- Collaboration features

## 3. Recently Completed

### 3.1. gitignore-based File Sync

Implemented in v0.2.0:

- Automatic .gitignore pattern support
- Matches Databricks CLI behavior
- User-configurable exclude patterns

## 4. Contributing

Feature requests and contributions are welcome. Please open an issue to discuss before implementing major changes.
