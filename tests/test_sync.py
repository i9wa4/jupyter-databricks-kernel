"""Tests for FileSync."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from jupyter_databricks_kernel.sync import FileSync


@pytest.fixture
def mock_config() -> MagicMock:
    """Create a mock config."""
    config = MagicMock()
    config.sync.enabled = True
    config.sync.source = "./src"
    config.sync.exclude = []
    return config


@pytest.fixture
def file_sync(mock_config: MagicMock) -> FileSync:
    """Create a FileSync instance with mock config."""
    return FileSync(mock_config, "test-session")


@pytest.fixture
def file_sync_with_patterns(mock_config: MagicMock) -> FileSync:
    """Create a FileSync instance with exclude patterns."""
    mock_config.sync.exclude = [
        "*.pyc",
        "__pycache__",
        ".git",
        ".venv/**",
        "data/*.csv",
        "**/*.log",
    ]
    return FileSync(mock_config, "test-session")


class TestSanitizePathComponent:
    """Tests for _sanitize_path_component method."""

    def test_normal_email_unchanged(self, file_sync: FileSync) -> None:
        """Test that normal email addresses are mostly unchanged."""
        result = file_sync._sanitize_path_component("user@example.com")
        assert result == "user@example.com"

    def test_removes_path_traversal(self, file_sync: FileSync) -> None:
        """Test that path traversal sequences are removed."""
        result = file_sync._sanitize_path_component("../../admin")
        assert ".." not in result
        # Slashes become underscores, so result is "__admin"
        assert "/" not in result

    def test_replaces_slashes(self, file_sync: FileSync) -> None:
        """Test that slashes are replaced."""
        result = file_sync._sanitize_path_component("user/name")
        assert "/" not in result
        assert result == "user_name"

    def test_replaces_backslashes(self, file_sync: FileSync) -> None:
        """Test that backslashes are replaced."""
        result = file_sync._sanitize_path_component("user\\name")
        assert "\\" not in result
        assert result == "user_name"

    def test_handles_complex_traversal(self, file_sync: FileSync) -> None:
        """Test complex path traversal attempts."""
        result = file_sync._sanitize_path_component("../../../etc/passwd")
        assert ".." not in result
        assert "/" not in result

    def test_removes_special_characters(self, file_sync: FileSync) -> None:
        """Test that special characters are removed."""
        result = file_sync._sanitize_path_component("user<>:\"'|?*name")
        # Only alphanumeric, dots, hyphens, underscores, and @ allowed
        assert all(c.isalnum() or c in "._@-" for c in result)

    def test_empty_becomes_unknown(self, file_sync: FileSync) -> None:
        """Test that empty string becomes 'unknown'."""
        result = file_sync._sanitize_path_component("")
        assert result == "unknown"

    def test_only_dots_becomes_unknown(self, file_sync: FileSync) -> None:
        """Test that string of only dots becomes 'unknown'."""
        result = file_sync._sanitize_path_component("...")
        assert result == "unknown"

    def test_strips_leading_trailing_dots(self, file_sync: FileSync) -> None:
        """Test that leading/trailing dots are stripped."""
        result = file_sync._sanitize_path_component(".user.")
        assert not result.startswith(".")
        assert not result.endswith(".")


class TestShouldExclude:
    """Tests for _should_exclude method with pathspec patterns."""

    def test_exclude_pyc_files(
        self, file_sync_with_patterns: FileSync, tmp_path: Path
    ) -> None:
        """Test that *.pyc pattern excludes .pyc files."""
        pyc_file = tmp_path / "module.pyc"
        pyc_file.touch()
        assert file_sync_with_patterns._should_exclude(pyc_file, tmp_path) is True

    def test_exclude_pycache_directory(
        self, file_sync_with_patterns: FileSync, tmp_path: Path
    ) -> None:
        """Test that __pycache__ pattern excludes the directory."""
        pycache_dir = tmp_path / "__pycache__"
        pycache_dir.mkdir()
        assert file_sync_with_patterns._should_exclude(pycache_dir, tmp_path) is True

    def test_exclude_git_directory(
        self, file_sync_with_patterns: FileSync, tmp_path: Path
    ) -> None:
        """Test that .git pattern excludes the directory."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        assert file_sync_with_patterns._should_exclude(git_dir, tmp_path) is True

    def test_exclude_venv_recursive(
        self, file_sync_with_patterns: FileSync, tmp_path: Path
    ) -> None:
        """Test that .venv/** pattern excludes files in .venv directory."""
        venv_dir = tmp_path / ".venv" / "lib"
        venv_dir.mkdir(parents=True)
        venv_file = venv_dir / "python.py"
        venv_file.touch()
        assert file_sync_with_patterns._should_exclude(venv_file, tmp_path) is True

    def test_exclude_data_csv(
        self, file_sync_with_patterns: FileSync, tmp_path: Path
    ) -> None:
        """Test that data/*.csv pattern excludes CSV files in data directory."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        csv_file = data_dir / "large.csv"
        csv_file.touch()
        assert file_sync_with_patterns._should_exclude(csv_file, tmp_path) is True

    def test_exclude_recursive_log(
        self, file_sync_with_patterns: FileSync, tmp_path: Path
    ) -> None:
        """Test that **/*.log pattern excludes log files anywhere."""
        logs_dir = tmp_path / "logs" / "2024"
        logs_dir.mkdir(parents=True)
        log_file = logs_dir / "app.log"
        log_file.touch()
        assert file_sync_with_patterns._should_exclude(log_file, tmp_path) is True

    def test_include_normal_python_file(
        self, file_sync_with_patterns: FileSync, tmp_path: Path
    ) -> None:
        """Test that normal Python files are not excluded."""
        py_file = tmp_path / "main.py"
        py_file.touch()
        assert file_sync_with_patterns._should_exclude(py_file, tmp_path) is False

    def test_include_non_matching_csv(
        self, file_sync_with_patterns: FileSync, tmp_path: Path
    ) -> None:
        """Test that CSV files outside data directory are not excluded."""
        csv_file = tmp_path / "results.csv"
        csv_file.touch()
        assert file_sync_with_patterns._should_exclude(csv_file, tmp_path) is False

    def test_empty_exclude_patterns(self, file_sync: FileSync, tmp_path: Path) -> None:
        """Test that empty exclude patterns don't exclude anything."""
        py_file = tmp_path / "main.py"
        py_file.touch()
        assert file_sync._should_exclude(py_file, tmp_path) is False
