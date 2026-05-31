"""Tests for runner.py (M3)."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from jupyter_databricks_kernel.executor import ExecutionResult
from jupyter_databricks_kernel.runner import (
    cli_run,
    cli_run_db_py,
    cli_run_ipynb,
    cli_run_py,
    detect_run_format,
    run_db_py,
    run_file,
    run_ipynb,
    run_py,
    write_output,
)

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_executor(output: str = "ok-output", error: str | None = None) -> MagicMock:
    """Return a minimal mock executor whose execute() returns a fixed result."""
    executor = MagicMock()
    status = "error" if error else "ok"
    executor.execute.return_value = ExecutionResult(
        status=status, output=output, error=error
    )
    return executor


# ---------------------------------------------------------------------------
# run format dispatch
# ---------------------------------------------------------------------------


class TestRunFormatDispatch:
    """Tests for unified runner format dispatch."""

    def test_detects_py_file(self, tmp_path: Path) -> None:
        """Plain .py files dispatch to the py runner."""
        assert detect_run_format(tmp_path / "script.py") == "py"

    def test_detects_db_py_before_plain_py(self, tmp_path: Path) -> None:
        """Databricks .db.py files dispatch to the db-py runner."""
        assert detect_run_format(tmp_path / "notebook.db.py") == "db-py"

    def test_detects_ipynb_file(self, tmp_path: Path) -> None:
        """Notebook files dispatch to the ipynb runner."""
        assert detect_run_format(tmp_path / "notebook.ipynb") == "ipynb"

    def test_explicit_format_overrides_extension(self, tmp_path: Path) -> None:
        """The --format equivalent overrides extension-based detection."""
        assert detect_run_format(tmp_path / "script.py", "db-py") == "db-py"

    def test_rejects_unknown_extension(self, tmp_path: Path) -> None:
        """Unsupported extensions fail with an actionable error."""
        with pytest.raises(ValueError, match="Cannot infer runner format"):
            detect_run_format(tmp_path / "notes.txt")

    def test_run_file_dispatches_to_db_py(self, tmp_path: Path) -> None:
        """run_file dispatches to the selected runner implementation."""
        py_file = tmp_path / "notebook.db.py"
        py_file.write_text("print('db')\n")
        executor = _make_executor()

        result = run_file(py_file, executor)

        assert result.status == "ok"
        executor.execute.assert_called_once_with("print('db')\n", timeout=None)

    def test_run_file_rejects_inplace_for_non_notebook(self, tmp_path: Path) -> None:
        """--inplace is only valid for ipynb execution."""
        py_file = tmp_path / "script.py"
        py_file.write_text("print('py')\n")

        with pytest.raises(ValueError, match="--inplace"):
            run_file(py_file, _make_executor(), inplace=True)


# ---------------------------------------------------------------------------
# run_py
# ---------------------------------------------------------------------------


class TestRunPy:
    """Tests for run_py()."""

    def test_reads_file_and_executes(self, tmp_path: Path) -> None:
        """run_py reads the file and passes its content to executor.execute."""
        py_file = tmp_path / "script.py"
        py_file.write_text("x = 1\n")
        executor = _make_executor()

        result = run_py(py_file, executor)

        executor.execute.assert_called_once_with("x = 1\n", timeout=None)
        assert result.status == "ok"

    def test_returns_execution_result(self, tmp_path: Path) -> None:
        """run_py returns the ExecutionResult from the executor."""
        py_file = tmp_path / "hello.py"
        py_file.write_text("print('hi')\n")
        executor = _make_executor(output="hi")

        result = run_py(py_file, executor)
        assert result.output == "hi"


# ---------------------------------------------------------------------------
# run_db_py
# ---------------------------------------------------------------------------


class TestRunDbPy:
    """Tests for run_db_py()."""

    def test_reads_file_and_executes(self, tmp_path: Path) -> None:
        """run_db_py reads the file and passes its content to executor.execute."""
        py_file = tmp_path / "notebook.py"
        py_file.write_text("# Databricks notebook\nprint('db')\n")
        executor = _make_executor()

        result = run_db_py(py_file, executor)

        executor.execute.assert_called_once_with(
            "# Databricks notebook\nprint('db')\n", timeout=None
        )
        assert result.status == "ok"

    def test_identical_behavior_to_run_py(self, tmp_path: Path) -> None:
        """run_db_py and run_py produce the same result for the same file."""
        py_file = tmp_path / "both.py"
        py_file.write_text("print('same')\n")

        executor_a = _make_executor(output="same")
        executor_b = _make_executor(output="same")

        result_py = run_py(py_file, executor_a)
        result_db = run_db_py(py_file, executor_b)

        assert result_py.status == result_db.status
        assert result_py.output == result_db.output


# ---------------------------------------------------------------------------
# run_ipynb
# ---------------------------------------------------------------------------


class TestRunIpynb:
    """Tests for run_ipynb()."""

    def _minimal_notebook(self, cells: list[str]) -> dict:
        """Build a minimal nbformat 4 notebook dict."""
        return {
            "nbformat": 4,
            "nbformat_minor": 5,
            "metadata": {},
            "cells": [
                {
                    "cell_type": "code",
                    "execution_count": None,
                    "metadata": {},
                    "outputs": [],
                    "source": [src],
                }
                for src in cells
            ],
        }

    def test_executes_all_code_cells(self, tmp_path: Path) -> None:
        """run_ipynb calls executor.execute for each code cell."""
        nb = self._minimal_notebook(["print('a')", "print('b')"])
        nb_path = tmp_path / "test.ipynb"
        nb_path.write_text(json.dumps(nb))
        executor = _make_executor(output="x")

        run_ipynb(nb_path, executor)

        assert executor.execute.call_count == 2

    def test_returns_summary_execution_result(self, tmp_path: Path) -> None:
        """run_ipynb returns a summary ExecutionResult."""
        nb = self._minimal_notebook(["print('c1')", "print('c2')"])
        nb_path = tmp_path / "test.ipynb"
        nb_path.write_text(json.dumps(nb))
        executor = _make_executor(output="out")

        result = run_ipynb(nb_path, executor)
        assert result.status == "ok"

    def test_skips_non_code_cells(self, tmp_path: Path) -> None:
        """run_ipynb skips markdown cells."""
        nb = {
            "nbformat": 4,
            "nbformat_minor": 5,
            "metadata": {},
            "cells": [
                {
                    "cell_type": "markdown",
                    "metadata": {},
                    "source": ["# header"],
                },
                {
                    "cell_type": "code",
                    "execution_count": None,
                    "metadata": {},
                    "outputs": [],
                    "source": ["print('code')"],
                },
            ],
        }
        nb_path = tmp_path / "test.ipynb"
        nb_path.write_text(json.dumps(nb))
        executor = _make_executor(output="code")

        run_ipynb(nb_path, executor)
        assert executor.execute.call_count == 1

    def test_empty_notebook_returns_no_code_cells(self, tmp_path: Path) -> None:
        """run_ipynb on a notebook with no code cells returns a no-op result."""
        nb = {
            "nbformat": 4,
            "nbformat_minor": 5,
            "metadata": {},
            "cells": [
                {
                    "cell_type": "markdown",
                    "metadata": {},
                    "source": ["# only markdown"],
                }
            ],
        }
        nb_path = tmp_path / "empty.ipynb"
        nb_path.write_text(json.dumps(nb))
        executor = _make_executor()

        result = run_ipynb(nb_path, executor)
        executor.execute.assert_not_called()
        assert result.status == "ok"
        assert result.output == "(no code cells)"


# ---------------------------------------------------------------------------
# write_output
# ---------------------------------------------------------------------------


class TestWriteOutput:
    """Tests for write_output()."""

    def test_creates_outputs_dir_and_file(self, tmp_path: Path) -> None:
        """write_output creates .cache/outputs/<stem>.<timestamp>.output.md."""
        import os

        os.chdir(tmp_path)
        result = ExecutionResult(status="ok", output="hello")
        source = tmp_path / "script.py"

        out_path = write_output(result, source)

        assert out_path.parent.resolve() == (tmp_path / ".cache" / "outputs").resolve()
        assert out_path.name.startswith("script.py.")
        assert out_path.name.endswith(".output.md")
        assert out_path.exists()

    def test_markdown_contains_status_and_output(self, tmp_path: Path) -> None:
        """write_output writes status and output sections."""
        import os

        os.chdir(tmp_path)
        result = ExecutionResult(status="ok", output="42")
        source = tmp_path / "calc.py"

        out_path = write_output(result, source)
        text = out_path.read_text()

        assert "**Status:** ok" in text
        assert "42" in text

    def test_error_section_present_when_error(self, tmp_path: Path) -> None:
        """write_output includes an Error section when result.error is set."""
        import os

        os.chdir(tmp_path)
        result = ExecutionResult(status="error", error="NameError: x")
        source = tmp_path / "bad.py"

        out_path = write_output(result, source)
        text = out_path.read_text()

        assert "## Error" in text
        assert "NameError: x" in text

    def test_no_error_section_when_no_error(self, tmp_path: Path) -> None:
        """write_output omits Error section when result.error is None."""
        import os

        os.chdir(tmp_path)
        result = ExecutionResult(status="ok", output="fine")
        source = tmp_path / "good.py"

        out_path = write_output(result, source)
        text = out_path.read_text()

        assert "## Error" not in text

    def test_returns_output_path(self, tmp_path: Path) -> None:
        """write_output returns the path to the written file."""
        import os

        os.chdir(tmp_path)
        result = ExecutionResult(status="ok")
        source = tmp_path / "myfile.py"

        out_path = write_output(result, source)
        assert out_path.name.startswith("myfile.py.")
        assert out_path.name.endswith(".output.md")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCliRun:
    """Tests for unified CLI behavior."""

    def test_unified_cli_dispatches_by_extension(self, tmp_path: Path) -> None:
        """cli_run infers the runner from the input file extension."""
        import sys

        py_file = tmp_path / "script.py"
        py_file.write_text("print('cli')\n")
        output_dir = tmp_path / "outputs"
        executor = _make_executor(output="cli")

        with (
            patch.object(
                sys,
                "argv",
                ["run", str(py_file), "--output-dir", str(output_dir)],
            ),
            patch("jupyter_databricks_kernel.config.Config.load"),
            patch(
                "jupyter_databricks_kernel.executor.DatabricksExecutor",
                return_value=executor,
            ),
        ):
            cli_run()

        executor.create_context.assert_called_once_with()
        executor.execute.assert_called_once_with(
            "print('cli')\n", timeout=timedelta(seconds=600)
        )
        executor.destroy_context.assert_called_once_with()
        assert list(output_dir.glob("script.py.*.output.md"))

    def test_unified_cli_format_override(self, tmp_path: Path) -> None:
        """cli_run supports an explicit --format override."""
        import sys

        py_file = tmp_path / "notebook.py"
        py_file.write_text("print('db')\n")
        executor = _make_executor(output="db")

        with (
            patch.object(sys, "argv", ["run", "--format", "db-py", str(py_file)]),
            patch("jupyter_databricks_kernel.config.Config.load"),
            patch(
                "jupyter_databricks_kernel.executor.DatabricksExecutor",
                return_value=executor,
            ),
        ):
            cli_run()

        executor.execute.assert_called_once_with(
            "print('db')\n", timeout=timedelta(seconds=600)
        )

    def test_run_py_console_entry_alias_uses_py_format(
        self, tmp_path: Path
    ) -> None:
        """The run-py console entry keeps the legacy py default format."""
        import sys

        py_file = tmp_path / "script.txt"
        py_file.write_text("print('py alias')\n")
        output_dir = tmp_path / "outputs"
        executor = _make_executor(output="py alias")

        with (
            patch.object(
                sys,
                "argv",
                ["run-py", str(py_file), "--output-dir", str(output_dir)],
            ),
            patch("jupyter_databricks_kernel.config.Config.load"),
            patch(
                "jupyter_databricks_kernel.executor.DatabricksExecutor",
                return_value=executor,
            ),
        ):
            cli_run_py()

        executor.execute.assert_called_once_with(
            "print('py alias')\n", timeout=timedelta(seconds=600)
        )
        assert list(output_dir.glob("script.txt.*.output.md"))

    def test_run_db_py_console_entry_alias_uses_db_py_format(
        self, tmp_path: Path
    ) -> None:
        """The run-db-py console entry keeps the legacy db-py default format."""
        import sys

        py_file = tmp_path / "notebook.txt"
        py_file.write_text("# Databricks notebook\nprint('db alias')\n")
        output_dir = tmp_path / "outputs"
        executor = _make_executor(output="db alias")

        with (
            patch.object(
                sys,
                "argv",
                ["run-db-py", str(py_file), "--output-dir", str(output_dir)],
            ),
            patch("jupyter_databricks_kernel.config.Config.load"),
            patch(
                "jupyter_databricks_kernel.executor.DatabricksExecutor",
                return_value=executor,
            ),
        ):
            cli_run_db_py()

        executor.execute.assert_called_once_with(
            "# Databricks notebook\nprint('db alias')\n",
            timeout=timedelta(seconds=600),
        )
        assert list(output_dir.glob("notebook.txt.*.output.md"))

    def test_run_ipynb_console_entry_alias_uses_ipynb_format(
        self, tmp_path: Path
    ) -> None:
        """The run-ipynb console entry keeps the legacy ipynb default format."""
        import sys

        nb_path = tmp_path / "notebook.txt"
        nb_path.write_text(
            json.dumps(
                {
                    "nbformat": 4,
                    "nbformat_minor": 5,
                    "metadata": {},
                    "cells": [
                        {
                            "cell_type": "code",
                            "execution_count": None,
                            "metadata": {},
                            "outputs": [],
                            "source": ["print('ipynb alias')"],
                        }
                    ],
                }
            )
        )
        output_dir = tmp_path / "outputs"
        executor = _make_executor(output="ipynb alias")

        with (
            patch.object(
                sys,
                "argv",
                ["run-ipynb", str(nb_path), "--output-dir", str(output_dir)],
            ),
            patch("jupyter_databricks_kernel.config.Config.load"),
            patch(
                "jupyter_databricks_kernel.executor.DatabricksExecutor",
                return_value=executor,
            ),
        ):
            cli_run_ipynb()

        executor.execute.assert_called_once_with(
            "print('ipynb alias')", timeout=timedelta(seconds=600)
        )
        assert list(output_dir.glob("notebook.txt.*.output.md"))

    def test_serverless_flag_fails_fast_with_documented_limitation(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--serverless is accepted by the parser but not silently routed."""
        import sys

        py_file = tmp_path / "script.py"
        py_file.write_text("print('serverless')\n")

        with (
            patch.object(sys, "argv", ["run", "--serverless", str(py_file)]),
            pytest.raises(SystemExit) as exc_info,
        ):
            cli_run()

        assert exc_info.value.code == 2
        assert "--serverless is recognized" in capsys.readouterr().err
