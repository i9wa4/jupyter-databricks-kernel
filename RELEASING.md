# Releasing

## Prerequisites

- PyPI Trusted Publisher configured
- Write access to repository

## Release Process

1. Update version in `pyproject.toml`
2. Commit the change

   ```bash
   git commit -m "chore: bump version to X.Y.Z"
   ```

3. Create a tag

   ```bash
   git tag vX.Y.Z
   ```

4. Push to remote

   ```bash
   git push origin main --tags
   ```

## What Happens Automatically

When a tag matching `v*.*.*` is pushed:

1. GitHub Actions builds the package
2. Package is published to PyPI via Trusted Publishers
3. GitHub Release is created with auto-generated notes

## PyPI Trusted Publisher Setup

Configure at <https://pypi.org/manage/account/publishing/>

| Field | Value |
|-------|-------|
| Owner | `i9wa4` |
| Repository | `jupyter-databricks-kernel` |
| Workflow | `publish.yaml` |
| Environment | `pypi` |
