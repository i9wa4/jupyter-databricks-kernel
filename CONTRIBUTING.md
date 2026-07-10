# Contributing to jupyter-databricks-kernel

Thank you for your interest in contributing to
jupyter-databricks-kernel!

## 1. Development Setup

### 1.1. Prerequisites

- Python 3.11 or later
- [uv](https://docs.astral.sh/uv/) for dependency management
- [Nix](https://nixos.org/) (recommended, for pre-commit hooks)

### 1.2. With Nix (recommended)

```bash
nix develop
```

This installs all tools, syncs dependencies, and sets up
pre-commit hooks automatically.

### 1.3. Without Nix

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Sync Python dependencies
uv sync

# Run tests
uv run pytest
```

### 1.4. Available Commands

| Command              | Description          |
| -------------------- | -------------------- |
| `uv sync`            | Sync dependencies    |
| `uv run pytest`      | Run tests            |
| `uv run mypy src`    | Type check           |
| `uv run jupyter-lab` | Start JupyterLab     |

### 1.5. Dependency Freshness Policy

`pyproject.toml` sets `[tool.uv] exclude-newer = "3 days"`, so `uv lock` and
`uv sync`/`uv add` (when they need to re-resolve) refuse any package version
published in the last 3 days. This is a supply-chain guard: it gives the
community a short window to catch and report compromised or buggy releases
before this project can adopt them, mirroring npm/pnpm's `minimumReleaseAge`.
Background: [この記事](https://zenn.dev/watany/articles/a81a6122864539)
("これ入れたい。3daysで" — "I want to incorporate this, within 3 days" — was the
original request that started this).

The 3-day window is intentionally aligned to `.github/dependabot.yml`'s
minimum `semver-patch-days: 3` cooldown tier, not its `default-days: 7`
tier: `exclude-newer` only needs to be old enough to admit any version
Dependabot could plausibly have already opened a PR for, and 3 days is the
tightest tier Dependabot uses. A wider window (e.g. 7 days) would let CI's
non-frozen `uv run pytest` re-resolve refuse a patch-level version
Dependabot already proposed at day 3.

This applies to the root package only. `examples/table-exporter` is a
separately-locked demo project and does not currently have a matching
`exclude-newer` setting or lock-check coverage (tracked as a fast-follow).

If `uv add`/`uv lock` unexpectedly refuses a package you need, it is
almost always because the version was published within the last 3 days —
wait a few days, or use `exclude-newer-package` to override the cutoff for
that one package if there is a specific reason to trust it early.

## 2. Project Structure

```text
src/jupyter_databricks_kernel/
├── kernel.py      # Jupyter kernel implementation
├── executor.py    # Databricks execution context management
├── sync.py        # File synchronization via Command API Base64 transfer
└── config.py      # Configuration loading and validation
```

| Module      | Description                                             |
| ----------- | ------------------------------------------------------- |
| kernel.py   | Kernel lifecycle, file sync, result formatting          |
| executor.py | Command Execution API, context management, reconnection |
| sync.py     | File collection, hash-based change detection, Command API transfer |
| config.py   | Environment variables, YAML config, validation          |

## 3. Code Style

This project uses automated tools for code quality.

### 3.1. Linting and Formatting

We use [Ruff](https://docs.astral.sh/ruff/) for linting and
formatting:

```bash
uv run ruff check src/
uv run ruff format src/
```

### 3.2. Type Checking

We use [mypy](https://mypy.readthedocs.io/) for static type
checking:

```bash
uv run mypy src/
```

### 3.3. Style Guidelines

- Follow PEP 8
- Use type hints for all function signatures
- Keep functions focused and small
- Write docstrings for public APIs

## 4. Testing

### 4.1. Running Tests

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=jupyter_databricks_kernel

# Run specific test file
uv run pytest tests/test_config.py -v
```

### 4.2. Writing Tests

- Place tests in the `tests/` directory
- Use descriptive test names:
  `test_validate_returns_error_when_cluster_id_missing`
- Mock external dependencies (Databricks API calls)
- Test both success and error cases

## 5. Local Kernel Installation for Debugging

During development, you may want to test the kernel locally:

```bash
# Install the kernel in development mode
uv run python -m jupyter_databricks_kernel.install

# Verify installation
uv run jupyter kernelspec list
```

To uninstall:

```bash
uv run jupyter kernelspec uninstall databricks
```

## 6. Using Development Version in Another Project

When developing features, you may want to test the kernel in a
separate project.

### 6.1. With uv (Recommended)

Add the following to your project's `pyproject.toml`:

```toml
[dependency-groups]
dev = [
    "jupyter-databricks-kernel",
    "jupyterlab",
]

[tool.uv.sources]
jupyter-databricks-kernel = { path = "../path/to/kernel", editable = true }
```

Then sync:

```bash
uv sync
```

To update after making changes to the kernel:

```bash
uv sync  # Re-syncs the editable install
```

**Note**: You must restart the Jupyter kernel after updating to
load the new code.

### 6.2. With uv add

```bash
uv add --dev --editable /path/to/jupyter-databricks-kernel
```

### 6.3. Verifying the Version

Check that the correct version is installed:

```bash
uv run python -c "import jupyter_databricks_kernel; \
  print(jupyter_databricks_kernel.__version__)"
```

Development versions will show a version like
`1.1.3.dev3+gbe2d703f8.d20251212`.

## 7. Pull Request Guidelines

### 7.1. Before Submitting

- Run `uv run pytest` and ensure all tests pass
- Run `uv run ruff check src/` and fix any issues
- Update documentation if needed
- Add tests for new functionality

### 7.2. PR Title and Description

- Use a clear, descriptive title
- Explain what the PR does and why
- Reference related issues (e.g., "Fixes #123")

### 7.3. Review Process

- PRs require at least one approval before merging
- Address reviewer feedback promptly
- Keep PRs focused on a single concern

## 8. Issue Reporting

### 8.1. Bug Reports

When reporting bugs, please include:

- Python version and OS
- Databricks Runtime version
- Steps to reproduce
- Expected vs actual behavior
- Error messages and stack traces

### 8.2. Feature Requests

When requesting features, please include:

- Use case description
- Proposed solution (if any)
- Alternatives considered

## 9. License

By contributing to this project, you agree that your
contributions will be licensed under the Apache License 2.0.
