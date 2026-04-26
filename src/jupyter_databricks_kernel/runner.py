"""CLI runner and library interface for Databricks code execution."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .executor import DatabricksExecutor, ExecutionResult


def run_py(path: Path, executor: DatabricksExecutor) -> ExecutionResult:
    """Execute a plain Python file on the Databricks cluster.

    Args:
        path: Path to the .py file to execute.
        executor: Initialized DatabricksExecutor with an active context.

    Returns:
        ExecutionResult from the cluster.
    """
    code = path.read_text(encoding="utf-8")
    return executor.execute(code)


def run_db_py(path: Path, executor: DatabricksExecutor) -> ExecutionResult:
    """Execute a Databricks notebook .py file on the cluster.

    Databricks .py notebooks are valid Python; magic command splitting
    (e.g. %run, %pip) is deferred to a future milestone.

    Args:
        path: Path to the Databricks .py notebook file.
        executor: Initialized DatabricksExecutor with an active context.

    Returns:
        ExecutionResult from the cluster.
    """
    code = path.read_text(encoding="utf-8")
    return executor.execute(code)


def run_ipynb(path: Path, executor: DatabricksExecutor) -> ExecutionResult:
    """Execute all code cells of a notebook and return combined output.

    Does NOT modify the notebook file. Use cli_run_ipynb with --inplace to
    write cell outputs back to the notebook.

    Args:
        path: Path to the .ipynb notebook to execute.
        executor: Initialized DatabricksExecutor with an active context.

    Returns:
        Summary ExecutionResult with combined output from all cells.
    """
    with open(path, encoding="utf-8") as f:
        notebook: dict[str, Any] = json.load(f)

    cells = notebook.get("cells", [])
    combined_output: list[str] = []
    last_result = None

    for cell in cells:
        if cell.get("cell_type") != "code":
            continue
        source = cell.get("source", "")
        if isinstance(source, list):
            source = "".join(source)
        if not source.strip():
            continue

        result = executor.execute(source)
        last_result = result

        if result.output:
            combined_output.append(result.output)
        if result.error:
            combined_output.append(f"ERROR: {result.error}")

    from .executor import ExecutionResult

    if last_result is None:
        return ExecutionResult(status="ok", output="(no code cells)")

    return ExecutionResult(
        status=last_result.status,
        output="\n".join(combined_output) if combined_output else None,
        error=last_result.error,
    )


def _run_ipynb_inplace(path: Path, executor: DatabricksExecutor) -> ExecutionResult:
    """Execute notebook cells and write outputs back into the notebook file.

    Saves a backup at <path>.bak before mutating; restores on exception.

    Args:
        path: Path to the .ipynb notebook to execute in-place.
        executor: Initialized DatabricksExecutor with an active context.

    Returns:
        Summary ExecutionResult with combined output from all cells.
    """
    backup = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup)

    try:
        with open(path, encoding="utf-8") as f:
            notebook: dict[str, Any] = json.load(f)

        cells = notebook.get("cells", [])
        combined_output: list[str] = []
        last_result = None

        for cell in cells:
            if cell.get("cell_type") != "code":
                continue
            source = cell.get("source", "")
            if isinstance(source, list):
                source = "".join(source)
            if not source.strip():
                continue

            result = executor.execute(source)
            last_result = result

            cell_outputs: list[dict[str, Any]] = []
            if result.output:
                combined_output.append(result.output)
                cell_outputs.append(
                    {
                        "output_type": "stream",
                        "name": "stdout",
                        "text": result.output,
                    }
                )
            if result.error:
                combined_output.append(f"ERROR: {result.error}")
                cell_outputs.append(
                    {
                        "output_type": "error",
                        "ename": "ExecutionError",
                        "evalue": result.error,
                        "traceback": result.traceback or [],
                    }
                )
            cell["outputs"] = cell_outputs

        with open(path, "w", encoding="utf-8") as f:
            json.dump(notebook, f, indent=1, ensure_ascii=False)

        backup.unlink()

        from .executor import ExecutionResult

        if last_result is None:
            return ExecutionResult(status="ok", output="(no code cells)")

        return ExecutionResult(
            status=last_result.status,
            output="\n".join(combined_output) if combined_output else None,
            error=last_result.error,
        )

    except Exception:
        shutil.copy2(backup, path)
        backup.unlink()
        raise


def write_output(
    result: ExecutionResult, path: Path, output_dir: str = ".cache/outputs"
) -> Path:
    """Write an ExecutionResult to <output_dir>/<path.stem>.<timestamp>.output.md.

    The output directory is created (including parents) if it does not exist.

    Args:
        result: The ExecutionResult to write.
        path: The source file path (used to derive the output filename).
        output_dir: Directory to write output file into (default: ".cache/outputs").

    Returns:
        Path to the written output file.
    """
    outputs_dir = Path(output_dir)
    outputs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    out_path = outputs_dir / f"{path.stem}.{timestamp}.output.md"

    lines: list[str] = [
        f"# Output: {path.name}",
        "",
        f"**Status:** {result.status}",
    ]

    if result.output is not None:
        lines += ["", "## Output", "", result.output]

    if result.error is not None:
        lines += ["", "## Error", "", result.error]

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def _cli_dispatch(subcommand: str) -> None:
    """Shared dispatch logic for CLI entry points.

    Args:
        subcommand: One of 'run_py', 'run_db_py'.
    """
    import argparse
    import sys

    from .config import Config
    from .executor import DatabricksExecutor

    parser = argparse.ArgumentParser()
    parser.add_argument("file")
    parser.add_argument("--output-dir", default=".cache/outputs")
    parsed = parser.parse_args()
    file_path = Path(parsed.file)
    output_dir = parsed.output_dir

    config = Config.load()
    executor = DatabricksExecutor(config)
    executor.create_context()
    try:
        fn = {"run_py": run_py, "run_db_py": run_db_py, "run_ipynb": run_ipynb}[
            subcommand
        ]
        result = fn(file_path, executor)
        write_output(result, file_path, output_dir)
    finally:
        executor.destroy_context()
    if result.status == "error":
        sys.exit(1)


def cli_run_py() -> None:
    """CLI entry point for run-py.

    Usage: run-py <path> [--output-dir DIR]

    Executes a .py file on the cluster. Output is written to
    <output-dir>/<stem>.<YYYYMMDDTHHMMSS>.output.md (default output-dir:
    ".cache/outputs"). Default execution timeout is 10 minutes; the cluster
    command is cancelled on timeout. Exits with code 1 on error or timeout.
    """
    _cli_dispatch("run_py")


def cli_run_db_py() -> None:
    """CLI entry point for run-db-py.

    Usage: run-db-py <path> [--output-dir DIR]

    Executes a Databricks .py notebook on the cluster. Output is written to
    <output-dir>/<stem>.<YYYYMMDDTHHMMSS>.output.md (default output-dir:
    ".cache/outputs"). Default execution timeout is 10 minutes; the cluster
    command is cancelled on timeout. Exits with code 1 on error or timeout.
    """
    _cli_dispatch("run_db_py")


def cli_run_ipynb() -> None:
    """CLI entry point for run-ipynb.

    Usage: run-ipynb <path> [--inplace] [--output-dir DIR]

    Without --inplace: executes cells and writes combined output to
    <output-dir>/<stem>.<YYYYMMDDTHHMMSS>.output.md (default output-dir:
    ".cache/outputs").
    With --inplace: writes cell outputs back into the notebook (backup at
    <path>.bak).

    Default execution timeout per cell is 10 minutes; the cluster command is
    cancelled on timeout. Exits with code 1 on error or timeout.
    """
    import argparse
    import sys

    from .config import Config
    from .executor import DatabricksExecutor, ExecutionResult

    parser = argparse.ArgumentParser()
    parser.add_argument("file")
    parser.add_argument("--inplace", action="store_true")
    parser.add_argument("--output-dir", default=".cache/outputs")
    parsed = parser.parse_args()
    file_path = Path(parsed.file)
    inplace = parsed.inplace
    output_dir = parsed.output_dir

    config = Config.load()
    executor = DatabricksExecutor(config)
    executor.create_context()
    try:
        if inplace:
            try:
                result = _run_ipynb_inplace(file_path, executor)
            except Exception as e:
                result = ExecutionResult(status="error", error=str(e))
        else:
            result = run_ipynb(file_path, executor)
        write_output(result, file_path, output_dir)
    finally:
        executor.destroy_context()
    if result.status == "error":
        sys.exit(1)


if __name__ == "__main__":
    import sys

    from .config import Config
    from .executor import DatabricksExecutor

    subcommand = sys.argv[1]
    file_path = Path(sys.argv[2])
    config = Config.load()
    executor = DatabricksExecutor(config)
    executor.create_context()
    try:
        fn = {"run_py": run_py, "run_db_py": run_db_py, "run_ipynb": run_ipynb}[
            subcommand
        ]
        result = fn(file_path, executor)
        write_output(result, file_path)
    finally:
        executor.destroy_context()
