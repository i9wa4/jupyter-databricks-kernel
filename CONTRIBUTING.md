# Contributing to jupyter-databricks-kernel

Thank you for your interest in contributing to jupyter-databricks-kernel!

## 1. Development Setup

### 1.1. Prerequisites

- Python 3.11 or later
- [mise](https://mise.jdx.dev/) for tool version management

### 1.2. Installation

```bash
# Install mise
curl https://mise.run | sh

# Install mise-managed tools
make install

# Sync Python dependencies
make sync
```

### 1.3. Available Commands

| Command | Description |
|---------|-------------|
| `make install` | Install mise tools |
| `make sync` | Sync Python dependencies with uv |
| `make test` | Run tests |
| `make jupyter` | Start JupyterLab |

## 2. Project Structure

```text
src/jupyter_databricks_kernel/
├── kernel.py      # Jupyter kernel implementation
├── executor.py    # Databricks execution context management
├── sync.py        # File synchronization to DBFS
└── config.py      # Configuration loading and validation
```

| Module | Description |
|--------|-------------|
| kernel.py | Kernel lifecycle, file sync coordination, result formatting |
| executor.py | Command Execution API, context management, reconnection |
| sync.py | File collection, hash-based change detection, DBFS upload |
| config.py | Environment variables, YAML config, validation |

## 3. Code Style

This project uses automated tools for code quality.

### 3.1. Linting and Formatting

We use [Ruff](https://docs.astral.sh/ruff/) for linting and formatting:

```bash
# Run all pre-commit hooks
mise exec -- pre-commit run --all-files

# Run ruff directly
mise exec -- uv run ruff check src/
mise exec -- uv run ruff format src/
```

### 3.2. Type Checking

We use [mypy](https://mypy.readthedocs.io/) for static type checking:

```bash
mise exec -- uv run mypy src/
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
make test

# Run with coverage
mise exec -- uv run pytest --cov=jupyter_databricks_kernel

# Run specific test file
mise exec -- uv run pytest tests/test_config.py -v
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
mise exec -- uv run python -m jupyter_databricks_kernel.install

# Verify installation
jupyter kernelspec list
```

To uninstall:

```bash
jupyter kernelspec uninstall databricks-session
```

## 6. Pull Request Guidelines

### 6.1. Before Submitting

- Run `mise exec -- pre-commit run --all-files` and fix any issues
- Run `make test` and ensure all tests pass
- Update documentation if needed
- Add tests for new functionality

### 6.2. PR Title and Description

- Use a clear, descriptive title
- Explain what the PR does and why
- Reference related issues (e.g., "Fixes #123")

### 6.3. Review Process

- PRs require at least one approval before merging
- Address reviewer feedback promptly
- Keep PRs focused on a single concern

## 7. Issue Reporting

### 7.1. Bug Reports

When reporting bugs, please include:

- Python version and OS
- Databricks Runtime version
- Steps to reproduce
- Expected vs actual behavior
- Error messages and stack traces

### 7.2. Feature Requests

When requesting features, please include:

- Use case description
- Proposed solution (if any)
- Alternatives considered

## 8. License

By contributing to this project, you agree that your contributions will be
licensed under the Apache License 2.0.
