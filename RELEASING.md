# Releasing

## Prerequisites

- PyPI Trusted Publisher configured
- Write access to repository

## Version Management

This project uses [hatch-vcs](https://github.com/ofek/hatch-vcs) for automatic
version management. The package version is derived from git tags, so there is
no need to manually update `pyproject.toml`.

- Tag format: `vX.Y.Z` (e.g., `v0.2.0`)
- Package version: `X.Y.Z` (e.g., `0.2.0`)

## Release Process

1. Create a tag

   ```bash
   git tag vX.Y.Z
   ```

2. Push to remote

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
