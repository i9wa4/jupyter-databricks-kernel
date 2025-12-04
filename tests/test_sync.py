"""Tests for FileSync."""

from __future__ import annotations

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
