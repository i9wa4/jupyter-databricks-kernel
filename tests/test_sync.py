"""Tests for FileSync."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jupyter_databricks_kernel.sync import (
    CACHE_FILE_NAME,
    DEFAULT_EXCLUDE_PATTERNS,
    FileCache,
    FileSizeError,
    FileSync,
    SyncStats,
    get_cache_dir,
    get_project_hash,
)


@pytest.fixture
def mock_config() -> MagicMock:
    """Create a mock config."""
    config = MagicMock()
    config.sync.enabled = True
    config.sync.source = "./src"
    config.sync.exclude = []
    config.sync.use_gitignore = False
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


class TestGetCacheDir:
    """Tests for get_cache_dir function."""

    def test_default_cache_dir(self, tmp_path: Path) -> None:
        """Test default cache directory when XDG_CACHE_HOME is not set."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("pathlib.Path.home", return_value=tmp_path):
                cache_dir = get_cache_dir()
                expected = tmp_path / ".cache" / "jupyter-databricks-kernel"
                assert cache_dir == expected

    def test_with_xdg_cache_home(self, tmp_path: Path) -> None:
        """Test cache directory when XDG_CACHE_HOME is set."""
        with patch.dict(os.environ, {"XDG_CACHE_HOME": str(tmp_path)}):
            cache_dir = get_cache_dir()
            expected = tmp_path / "jupyter-databricks-kernel"
            assert cache_dir == expected

    def test_does_not_create_directory(self, tmp_path: Path) -> None:
        """Test that get_cache_dir does not create the directory."""
        xdg_cache = tmp_path / "custom_cache"
        with patch.dict(os.environ, {"XDG_CACHE_HOME": str(xdg_cache)}):
            cache_dir = get_cache_dir()
            # Directory should NOT be created by get_cache_dir
            assert not cache_dir.exists()


class TestGetProjectHash:
    """Tests for get_project_hash function."""

    def test_deterministic(self, tmp_path: Path) -> None:
        """Test that same path produces same hash."""
        hash1 = get_project_hash(tmp_path)
        hash2 = get_project_hash(tmp_path)
        assert hash1 == hash2

    def test_different_paths_produce_different_hashes(self, tmp_path: Path) -> None:
        """Test that different paths produce different hashes."""
        path1 = tmp_path / "project1"
        path2 = tmp_path / "project2"
        path1.mkdir()
        path2.mkdir()

        hash1 = get_project_hash(path1)
        hash2 = get_project_hash(path2)
        assert hash1 != hash2

    def test_hash_length(self, tmp_path: Path) -> None:
        """Test that hash is 16 characters."""
        project_hash = get_project_hash(tmp_path)
        assert len(project_hash) == 16

    def test_hash_is_hexadecimal(self, tmp_path: Path) -> None:
        """Test that hash contains only hexadecimal characters."""
        project_hash = get_project_hash(tmp_path)
        assert all(c in "0123456789abcdef" for c in project_hash)


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


class TestFileCache:
    """Tests for FileCache class."""

    def test_compute_hash(self, tmp_path: Path) -> None:
        """Test MD5 hash computation."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world")
        cache = FileCache(tmp_path)
        hash_value = cache.compute_hash(test_file)
        # MD5 of "hello world" is 5eb63bbbe01eeed093cb22bb8f5acdc3
        assert hash_value == "5eb63bbbe01eeed093cb22bb8f5acdc3"

    def test_get_changed_files_all_new(self, tmp_path: Path) -> None:
        """Test that all files are marked as changed when cache is empty."""
        file1 = tmp_path / "file1.py"
        file2 = tmp_path / "file2.py"
        file1.write_text("content1")
        file2.write_text("content2")

        cache = FileCache(tmp_path)
        changed, stats, computed_hashes = cache.get_changed_files([file1, file2])

        assert len(changed) == 2
        assert stats.changed_files == 2
        assert stats.skipped_files == 0
        assert stats.total_files == 2
        assert len(computed_hashes) == 2

    def test_get_changed_files_with_cache(self, tmp_path: Path) -> None:
        """Test that unchanged files are skipped."""
        file1 = tmp_path / "file1.py"
        file2 = tmp_path / "file2.py"
        file1.write_text("content1")
        file2.write_text("content2")

        cache = FileCache(tmp_path)
        cache.update([file1, file2])

        # Modify only file1
        file1.write_text("modified content")

        changed, stats, computed_hashes = cache.get_changed_files([file1, file2])

        assert len(changed) == 1
        assert file1 in changed
        assert file2 not in changed
        assert stats.changed_files == 1
        assert stats.skipped_files == 1
        assert len(computed_hashes) == 2

    def test_save_and_load_cache(self, tmp_path: Path) -> None:
        """Test cache persistence."""
        file1 = tmp_path / "file1.py"
        file1.write_text("content")

        # Create and save cache
        cache1 = FileCache(tmp_path)
        cache1.update([file1])
        cache1.save()

        # Verify cache file exists at XDG-compliant path
        assert cache1.cache_path.exists()

        # Load cache in new instance
        cache2 = FileCache(tmp_path)
        changed, stats, _ = cache2.get_changed_files([file1])

        # File should not be changed
        assert len(changed) == 0
        assert stats.skipped_files == 1

    def test_save_creates_directory(self, tmp_path: Path) -> None:
        """Test that save() creates cache directory if it doesn't exist."""
        xdg_cache = tmp_path / "custom_cache"
        with patch.dict(os.environ, {"XDG_CACHE_HOME": str(xdg_cache)}):
            file1 = tmp_path / "file1.py"
            file1.write_text("content")

            cache = FileCache(tmp_path)
            # Directory should not exist before save
            assert not cache.cache_path.parent.exists()

            cache.update([file1])
            cache.save()

            # Directory and file should exist after save
            assert cache.cache_path.parent.exists()
            assert cache.cache_path.parent.is_dir()
            assert cache.cache_path.exists()

    def test_cache_version_mismatch(self, tmp_path: Path) -> None:
        """Test that cache is reset on version mismatch."""
        file1 = tmp_path / "file1.py"
        file1.write_text("content")

        # Get cache path and create cache file with wrong version
        cache = FileCache(tmp_path)
        cache_file = cache.cache_path
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(
            json.dumps({"version": 999, "files": {"file1.py": "abc"}})
        )

        # Reload cache to pick up the corrupted file
        cache = FileCache(tmp_path)
        changed, stats, _ = cache.get_changed_files([file1])

        # File should be marked as changed due to version mismatch
        assert len(changed) == 1

    def test_cache_corruption_fallback(self, tmp_path: Path) -> None:
        """Test that corrupted cache falls back to empty."""
        file1 = tmp_path / "file1.py"
        file1.write_text("content")

        # Get cache path and create corrupted cache file
        cache = FileCache(tmp_path)
        cache_file = cache.cache_path
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text("not valid json {{{")

        cache = FileCache(tmp_path)
        changed, stats, _ = cache.get_changed_files([file1])

        # File should be marked as changed due to corrupted cache
        assert len(changed) == 1

    def test_clear_cache(self, tmp_path: Path) -> None:
        """Test cache clearing."""
        file1 = tmp_path / "file1.py"
        file1.write_text("content")

        cache = FileCache(tmp_path)
        cache.update([file1])

        # Verify file is cached
        changed, _, _ = cache.get_changed_files([file1])
        assert len(changed) == 0

        # Clear and verify
        cache.clear()
        changed, _, _ = cache.get_changed_files([file1])
        assert len(changed) == 1

    def test_changed_size_tracking(self, tmp_path: Path) -> None:
        """Test that changed file sizes are tracked."""
        file1 = tmp_path / "file1.py"
        content = "x" * 100
        file1.write_text(content)

        cache = FileCache(tmp_path)
        changed, stats, _ = cache.get_changed_files([file1])

        assert stats.changed_size == 100

    def test_has_any_changed_returns_true_on_change(self, tmp_path: Path) -> None:
        """Test that has_any_changed returns True when file is modified."""
        file1 = tmp_path / "file1.py"
        file1.write_text("content")

        cache = FileCache(tmp_path)
        cache.update([file1])

        # Modify the file
        file1.write_text("modified content")

        assert cache.has_any_changed([file1]) is True

    def test_has_any_changed_returns_false_when_unchanged(self, tmp_path: Path) -> None:
        """Test that has_any_changed returns False when no changes."""
        file1 = tmp_path / "file1.py"
        file1.write_text("content")

        cache = FileCache(tmp_path)
        cache.update([file1])

        assert cache.has_any_changed([file1]) is False

    def test_has_any_changed_returns_true_for_new_file(self, tmp_path: Path) -> None:
        """Test that has_any_changed returns True for uncached files."""
        file1 = tmp_path / "file1.py"
        file1.write_text("content")

        cache = FileCache(tmp_path)
        # Don't update cache - file is new

        assert cache.has_any_changed([file1]) is True

    def test_has_any_changed_returns_true_on_read_error(self, tmp_path: Path) -> None:
        """Test that has_any_changed returns True when file cannot be read."""
        file1 = tmp_path / "file1.py"
        file1.write_text("content")

        cache = FileCache(tmp_path)
        cache.update([file1])

        # Delete file to cause read error
        file1.unlink()

        # Read error should be treated as changed
        assert cache.has_any_changed([file1]) is True

    def test_update_reuses_computed_hashes(self, tmp_path: Path) -> None:
        """Test that update() reuses pre-computed hashes instead of recomputing."""
        file1 = tmp_path / "file1.py"
        file1.write_text("content")

        cache = FileCache(tmp_path)
        _, _, computed_hashes = cache.get_changed_files([file1])

        # Pass computed_hashes to update
        cache.update([file1], computed_hashes)

        # Verify cache contains the correct hash
        rel_path = "file1.py"
        assert cache._cache[rel_path] == computed_hashes[rel_path]


class TestValidateSizes:
    """Tests for file size validation."""

    @pytest.fixture
    def file_sync_with_size_limit(self, tmp_path: Path) -> FileSync:
        """Create a FileSync instance with size limits."""
        config = MagicMock()
        config.sync.enabled = True
        config.sync.source = str(tmp_path)
        config.sync.exclude = []
        config.sync.max_size_mb = 1.0  # 1MB total limit
        config.sync.max_file_size_mb = 0.5  # 0.5MB per file limit
        return FileSync(config, "test-session")

    @pytest.fixture
    def file_sync_no_limit(self, tmp_path: Path) -> FileSync:
        """Create a FileSync instance without size limits."""
        config = MagicMock()
        config.sync.enabled = True
        config.sync.source = str(tmp_path)
        config.sync.exclude = []
        config.sync.max_size_mb = None
        config.sync.max_file_size_mb = None
        return FileSync(config, "test-session")

    def test_validate_sizes_within_limits(
        self, file_sync_with_size_limit: FileSync, tmp_path: Path
    ) -> None:
        """Test that files within limits pass validation."""
        file1 = tmp_path / "small.txt"
        file1.write_bytes(b"x" * 1000)  # 1KB

        # Should not raise
        file_sync_with_size_limit._validate_sizes([file1], tmp_path)

    def test_validate_sizes_file_too_large(
        self, file_sync_with_size_limit: FileSync, tmp_path: Path
    ) -> None:
        """Test that single file exceeding limit raises error."""
        large_file = tmp_path / "large.txt"
        large_file.write_bytes(b"x" * (600 * 1024))  # 600KB > 0.5MB limit

        with pytest.raises(FileSizeError) as exc_info:
            file_sync_with_size_limit._validate_sizes([large_file], tmp_path)

        assert "large.txt" in str(exc_info.value)
        assert "exceeds limit" in str(exc_info.value)

    def test_validate_sizes_total_too_large(
        self, file_sync_with_size_limit: FileSync, tmp_path: Path
    ) -> None:
        """Test that total size exceeding limit raises error."""
        # Create multiple files that together exceed 1MB
        for i in range(3):
            file = tmp_path / f"file{i}.txt"
            file.write_bytes(b"x" * (400 * 1024))  # 400KB each = 1.2MB total

        files = list(tmp_path.glob("*.txt"))
        with pytest.raises(FileSizeError) as exc_info:
            file_sync_with_size_limit._validate_sizes(files, tmp_path)

        assert "Project size" in str(exc_info.value)
        assert "exceeds limit" in str(exc_info.value)

    def test_validate_sizes_no_limit(
        self, file_sync_no_limit: FileSync, tmp_path: Path
    ) -> None:
        """Test that no limits allows any size."""
        large_file = tmp_path / "large.txt"
        large_file.write_bytes(b"x" * (2 * 1024 * 1024))  # 2MB

        # Should not raise when no limits configured
        file_sync_no_limit._validate_sizes([large_file], tmp_path)


class TestFormatSize:
    """Tests for _format_size helper method."""

    def test_format_bytes(self, file_sync: FileSync) -> None:
        """Test formatting bytes."""
        assert file_sync._format_size(500) == "500 B"
        assert file_sync._format_size(0) == "0 B"

    def test_format_kilobytes(self, file_sync: FileSync) -> None:
        """Test formatting kilobytes."""
        assert file_sync._format_size(1024) == "1 KB"
        assert file_sync._format_size(2560) == "2.5 KB"

    def test_format_megabytes(self, file_sync: FileSync) -> None:
        """Test formatting megabytes."""
        assert file_sync._format_size(1024 * 1024) == "1 MB"
        assert file_sync._format_size(int(2.5 * 1024 * 1024)) == "2.5 MB"


class TestSyncStats:
    """Tests for SyncStats dataclass."""

    def test_default_values(self) -> None:
        """Test default values."""
        stats = SyncStats()
        assert stats.changed_files == 0
        assert stats.changed_size == 0
        assert stats.skipped_files == 0
        assert stats.total_files == 0
        assert stats.sync_duration == 0.0
        assert stats.dbfs_path == ""

    def test_with_values(self) -> None:
        """Test with custom values."""
        stats = SyncStats(
            changed_files=3,
            changed_size=1024,
            skipped_files=10,
            total_files=13,
            sync_duration=1.5,
            dbfs_path="/tmp/test/project.zip",
        )
        assert stats.changed_files == 3
        assert stats.changed_size == 1024
        assert stats.skipped_files == 10
        assert stats.total_files == 13
        assert stats.sync_duration == 1.5
        assert stats.dbfs_path == "/tmp/test/project.zip"


class TestDefaultExcludePatterns:
    """Tests for default exclude patterns matching Databricks CLI."""

    def test_contains_databricks_git_and_cache_file(self) -> None:
        """Test that .databricks, .git, and cache file are excluded."""
        assert ".databricks" in DEFAULT_EXCLUDE_PATTERNS
        assert ".git" in DEFAULT_EXCLUDE_PATTERNS
        assert CACHE_FILE_NAME in DEFAULT_EXCLUDE_PATTERNS


class TestGitignorePatternMatching:
    """Tests for .gitignore-based pattern matching."""

    @pytest.fixture
    def file_sync_with_gitignore(self, tmp_path: Path) -> FileSync:
        """Create a FileSync instance with use_gitignore enabled."""
        config = MagicMock()
        config.sync.enabled = True
        config.sync.source = str(tmp_path)
        config.sync.exclude = []
        config.sync.use_gitignore = True
        return FileSync(config, "test-session")

    @pytest.fixture
    def file_sync_without_gitignore(self, tmp_path: Path) -> FileSync:
        """Create a FileSync instance with use_gitignore disabled."""
        config = MagicMock()
        config.sync.enabled = True
        config.sync.source = str(tmp_path)
        config.sync.exclude = []
        config.sync.use_gitignore = False
        return FileSync(config, "test-session")

    def test_excludes_databricks_directory(
        self, file_sync: FileSync, tmp_path: Path
    ) -> None:
        """Test that .databricks directory is always excluded."""
        databricks_dir = tmp_path / ".databricks"
        databricks_dir.mkdir()

        assert file_sync._should_exclude(databricks_dir, tmp_path) is True

    def test_includes_normal_python_files(
        self, file_sync: FileSync, tmp_path: Path
    ) -> None:
        """Test that normal Python files are not excluded."""
        py_file = tmp_path / "main.py"
        py_file.touch()

        assert file_sync._should_exclude(py_file, tmp_path) is False

    def test_respects_gitignore(
        self, file_sync_with_gitignore: FileSync, tmp_path: Path
    ) -> None:
        """Test that .gitignore patterns are respected when use_gitignore is True."""
        # Create a .gitignore file
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.log\ndata/\n.env\n")

        # Create files
        log_file = tmp_path / "app.log"
        log_file.touch()
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        env_file = tmp_path / ".env"
        env_file.touch()

        # Force reload of gitignore
        file_sync_with_gitignore._pathspec = None

        assert file_sync_with_gitignore._should_exclude(log_file, tmp_path) is True
        assert file_sync_with_gitignore._should_exclude(data_dir, tmp_path) is True
        assert file_sync_with_gitignore._should_exclude(env_file, tmp_path) is True

    def test_does_not_exclude_without_gitignore(
        self, file_sync_with_gitignore: FileSync, tmp_path: Path
    ) -> None:
        """Test that files are included if .gitignore file doesn't exist."""
        # No .gitignore file
        env_file = tmp_path / ".env"
        env_file.touch()

        # Force reload
        file_sync_with_gitignore._pathspec = None

        # .env is NOT excluded without .gitignore file
        assert file_sync_with_gitignore._should_exclude(env_file, tmp_path) is False

    def test_user_exclude_patterns_applied(
        self, mock_config: MagicMock, tmp_path: Path
    ) -> None:
        """Test that user-configured exclude patterns are applied."""
        mock_config.sync.exclude = ["*.txt", "temp/"]
        file_sync = FileSync(mock_config, "test-session")

        txt_file = tmp_path / "notes.txt"
        txt_file.touch()

        assert file_sync._should_exclude(txt_file, tmp_path) is True

    def test_ignores_gitignore_when_disabled(
        self, file_sync_without_gitignore: FileSync, tmp_path: Path
    ) -> None:
        """Test that .gitignore patterns are ignored when use_gitignore is False."""
        # Create a .gitignore file
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.log\ndata/\n.env\n")

        # Create files that would be excluded by .gitignore
        log_file = tmp_path / "app.log"
        log_file.touch()
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        env_file = tmp_path / ".env"
        env_file.touch()

        # Force reload
        file_sync_without_gitignore._pathspec = None

        # These files should NOT be excluded because use_gitignore is False
        assert file_sync_without_gitignore._should_exclude(log_file, tmp_path) is False
        assert file_sync_without_gitignore._should_exclude(data_dir, tmp_path) is False
        assert file_sync_without_gitignore._should_exclude(env_file, tmp_path) is False

    def test_use_gitignore_default_is_true(self, tmp_path: Path) -> None:
        """Test that use_gitignore defaults to True."""
        from jupyter_databricks_kernel.config import Config

        config = Config()
        assert config.sync.use_gitignore is True


class TestFileDeletion:
    """Tests for file deletion detection."""

    def test_get_deleted_files_empty_when_no_deletions(self, tmp_path: Path) -> None:
        """Test that no deletions returns empty list."""
        file1 = tmp_path / "file1.py"
        file1.write_text("content")

        cache = FileCache(tmp_path)
        cache.update([file1])

        deleted = cache.get_deleted_files([file1])
        assert deleted == []

    def test_get_deleted_files_detects_deletion(self, tmp_path: Path) -> None:
        """Test that deleted files are detected."""
        file1 = tmp_path / "file1.py"
        file2 = tmp_path / "file2.py"
        file1.write_text("content1")
        file2.write_text("content2")

        cache = FileCache(tmp_path)
        cache.update([file1, file2])

        # Simulate file2 deletion by only passing file1
        deleted = cache.get_deleted_files([file1])
        assert "file2.py" in deleted

    def test_remove_file_from_cache(self, tmp_path: Path) -> None:
        """Test removing a file from cache."""
        file1 = tmp_path / "file1.py"
        file1.write_text("content")

        cache = FileCache(tmp_path)
        cache.update([file1])
        cache.remove("file1.py")

        # File should now be detected as changed (not in cache)
        changed, _, _ = cache.get_changed_files([file1])
        assert file1 in changed

    def test_get_deleted_files_multiple_deletions(self, tmp_path: Path) -> None:
        """Test detection of multiple deleted files."""
        files = [tmp_path / f"file{i}.py" for i in range(5)]
        for f in files:
            f.write_text(f"content of {f.name}")

        cache = FileCache(tmp_path)
        cache.update(files)

        # Keep only the first file
        deleted = cache.get_deleted_files([files[0]])
        assert len(deleted) == 4
        for i in range(1, 5):
            assert f"file{i}.py" in deleted


class TestNeedsSyncIntegration:
    """Integration tests for needs_sync() method."""

    def test_needs_sync_detects_file_deletion(
        self, mock_config: MagicMock, tmp_path: Path
    ) -> None:
        """Test that needs_sync returns True when files are deleted."""
        mock_config.sync.source = str(tmp_path)
        mock_config.sync.exclude = []
        file_sync = FileSync(mock_config, "test-session")

        # Create file and update cache
        file1 = tmp_path / "file1.py"
        file1.write_text("content")
        file_sync._get_file_cache().update([file1])
        file_sync._synced = True

        # Delete the file
        file1.unlink()

        # Should detect deletion and return True
        assert file_sync.needs_sync() is True

    def test_needs_sync_returns_false_when_no_changes(
        self, mock_config: MagicMock, tmp_path: Path
    ) -> None:
        """Test that needs_sync returns False when no files changed or deleted."""
        mock_config.sync.source = str(tmp_path)
        mock_config.sync.exclude = []
        file_sync = FileSync(mock_config, "test-session")

        # Create file and update cache
        file1 = tmp_path / "file1.py"
        file1.write_text("content")
        file_sync._get_file_cache().update([file1])
        file_sync._synced = True

        # No changes - should return False
        assert file_sync.needs_sync() is False

    def test_needs_sync_detects_file_modification(
        self, mock_config: MagicMock, tmp_path: Path
    ) -> None:
        """Test that needs_sync returns True when files are modified."""
        mock_config.sync.source = str(tmp_path)
        mock_config.sync.exclude = []
        file_sync = FileSync(mock_config, "test-session")

        # Create file and update cache
        file1 = tmp_path / "file1.py"
        file1.write_text("content")
        file_sync._get_file_cache().update([file1])
        file_sync._synced = True

        # Modify the file
        file1.write_text("modified content")

        # Should detect modification and return True
        assert file_sync.needs_sync() is True


class TestSkipNonRegularFiles:
    """Tests for skipping non-regular files (sockets, FIFOs, etc.)."""

    def test_get_all_files_skips_socket_files(self, mock_config: MagicMock) -> None:
        """Test that _get_all_files skips socket files."""
        import shutil
        import socket
        import tempfile

        # Use /tmp directly to avoid AF_UNIX path length limit on macOS
        test_dir = Path(tempfile.mkdtemp(prefix="sync_test_"))
        try:
            mock_config.sync.source = str(test_dir)
            mock_config.sync.exclude = []
            file_sync = FileSync(mock_config, "test-session")

            # Create a regular file
            regular_file = test_dir / "regular.py"
            regular_file.write_text("print('hello')")

            # Create a Unix socket file
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock_path = test_dir / "test.sock"
            sock.bind(str(sock_path))
            try:
                # Get all files - socket should be skipped
                files = file_sync._get_all_files()

                assert regular_file in files
                assert sock_path not in files
                assert len(files) == 1
            finally:
                sock.close()
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_create_zip_skips_socket_files(self, mock_config: MagicMock) -> None:
        """Test that _create_zip skips socket files without error."""
        import io
        import shutil
        import socket
        import tempfile
        import zipfile

        # Use /tmp directly to avoid AF_UNIX path length limit on macOS
        test_dir = Path(tempfile.mkdtemp(prefix="sync_test_"))
        try:
            mock_config.sync.source = str(test_dir)
            mock_config.sync.exclude = []
            file_sync = FileSync(mock_config, "test-session")

            # Create a regular file
            regular_file = test_dir / "regular.py"
            regular_file.write_text("print('hello')")

            # Create a Unix socket file
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock_path = test_dir / "test.sock"
            sock.bind(str(sock_path))
            try:
                # Create zip - should not raise error
                zip_data = file_sync._create_zip()

                # Verify zip contains only regular file
                with zipfile.ZipFile(io.BytesIO(zip_data), "r") as zf:
                    names = zf.namelist()
                    assert "regular.py" in names
                    assert "test.sock" not in names
                    assert len(names) == 1
            finally:
                sock.close()
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)
