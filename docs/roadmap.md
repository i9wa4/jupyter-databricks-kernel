# Roadmap

## Planned Features

### Differential Sync (rsync-style)

Currently, the kernel uploads all files as a ZIP archive. A future improvement would sync only changed files incrementally:

- Reduce sync time for large projects
- Lower bandwidth usage
- Faster iteration cycles

### Improved Error Messages

Enhance error reporting with:

- Clearer authentication error messages
- Better context for cluster errors
- Suggestions for common issues

### Configurable Timeouts

Allow users to configure:

- Context creation timeout
- Command execution timeout
- Reconnection delay

### Progress Indicators

Show progress for:

- File synchronization
- Cluster startup
- Long-running operations

## Under Consideration

### Multiple Cluster Support

Ability to switch between clusters within a session:

```yaml
clusters:
  default: "cluster-1"
  gpu: "gpu-cluster"
  large: "high-memory-cluster"
```

### Serverless Support

Pending Databricks API support for Command Execution on serverless compute. Currently blocked by API limitations.

### State Persistence

Optional serialization of session state:

- Checkpoint variables
- Restore on reconnection
- Reduce re-execution after cluster restart

### Workspace Integration

Better integration with Databricks Workspace:

- Sync to Repos instead of user directory
- Git integration
- Collaboration features

## Recently Completed

### gitignore-based File Sync

Implemented in v0.2.0:

- Automatic .gitignore pattern support
- Matches Databricks CLI behavior
- User-configurable exclude patterns

## Contributing

Feature requests and contributions are welcome. Please open an issue to discuss before implementing major changes.
