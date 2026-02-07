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

### Recommended: GitHub Actions Dispatch

1. Go to Actions > Release > Run workflow
2. Select `main` branch
3. Enter version (e.g., `v1.3.0`)
4. Click "Run workflow"

The workflow validates the version format, checks for duplicate tags,
creates a GitHub Release with the tag, and publishes to PyPI automatically.

### Alternative: Manual Tag Push

1. Create a tag

   ```bash
   git tag vX.Y.Z
   ```

2. Push to remote

   ```bash
   git push origin main --tags
   ```

## What Happens Automatically

### Via Dispatch (Recommended)

1. Version format validated (`vX.Y.Z`)
2. Branch validated (must be `main`)
3. Tag uniqueness checked
4. GitHub Release created with auto-generated notes
5. Package built and published to PyPI via Trusted Publishers

### Via Tag Push (Alternative)

When a tag matching `v*.*.*` is pushed:

1. GitHub Release created with auto-generated notes
2. Package built and published to PyPI via Trusted Publishers

## PyPI Trusted Publisher Setup

Configure at <https://pypi.org/manage/account/publishing/>

| Field       | Value                        |
| ----------- | ---------------------------- |
| Owner       | `i9wa4`                      |
| Repository  | `jupyter-databricks-kernel`  |
| Workflow    | `publish.yaml`               |
| Environment | `pypi`                       |
