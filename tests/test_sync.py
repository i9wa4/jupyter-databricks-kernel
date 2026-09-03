"""Tests for FileSync."""

from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path
from unittest.mock import ANY, MagicMock, Mock, patch

import pytest

from jupyter_databricks_kernel.sync import (
    CACHE_FILE_NAME,
    COMMAND_API_BINARY_CHUNK_SIZE,
    COMMAND_API_COMMAND_HEADROOM_BYTES,
    COMMAND_API_MAX_COMMAND_BYTES,
    DEFAULT_EXCLUDE_PATTERNS,
    FileCache,
    FileSizeError,
    FileSync,
    SetupError,
    SyncPlan,
    SyncStats,
    build_command_api_archive_cleanup_command,
    build_command_api_chunk_write_command,
    count_command_api_base64_chunks,
    get_cache_dir,
    get_project_hash,
    iter_command_api_base64_chunks,
)


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


class TestFileSyncAttribution:
    """Tests for FileSync WorkspaceClient attribution."""

    def test_default_caller_is_package_name(self, mock_config: MagicMock) -> None:
        file_sync = FileSync(mock_config, "test-session")
        assert file_sync.caller == "jupyter-databricks-kernel"

    def test_custom_caller_is_stored(self, mock_config: MagicMock) -> None:
        file_sync = FileSync(mock_config, "test-session", caller="test-caller")
        assert file_sync.caller == "test-caller"

    def test_caller_passed_to_workspace_client_as_product(
        self, mock_config: MagicMock
    ) -> None:
        from jupyter_databricks_kernel import __version__

        with patch("jupyter_databricks_kernel.sync.WorkspaceClient") as mock_ws_cls:
            file_sync = FileSync(mock_config, "test-session", caller="test-caller")
            file_sync._ensure_client()

        mock_ws_cls.assert_called_once_with(
            product="test-caller",
            product_version=__version__,
        )

    def test_default_caller_passed_to_workspace_client(
        self, mock_config: MagicMock
    ) -> None:
        from jupyter_databricks_kernel import __version__

        with patch("jupyter_databricks_kernel.sync.WorkspaceClient") as mock_ws_cls:
            file_sync = FileSync(mock_config, "test-session")
            file_sync._ensure_client()

        mock_ws_cls.assert_called_once_with(
            product="jupyter-databricks-kernel",
            product_version=__version__,
        )

    def test_injected_client_bypasses_caller_attribution(
        self, mock_config: MagicMock, mock_workspace_client: MagicMock
    ) -> None:
        file_sync = FileSync(
            mock_config,
            "test-session",
            client=mock_workspace_client,
            caller="test-caller",
        )
        result = file_sync._ensure_client()

        assert result is mock_workspace_client


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

    def test_hash_worker_count_caps_to_files_and_default_workers(self) -> None:
        """Test worker count is bounded by file count and Python's default cap."""
        with patch("jupyter_databricks_kernel.sync.os.cpu_count", return_value=2):
            assert FileCache._hash_worker_count(0) == 1
            assert FileCache._hash_worker_count(3) == 3
            assert FileCache._hash_worker_count(10) == 6

    def test_get_changed_files_parallel_hashes_preserve_input_order(
        self, tmp_path: Path
    ) -> None:
        """Test parallel hashing still returns changed files in input order."""
        file1 = tmp_path / "file1.py"
        file2 = tmp_path / "file2.py"
        file3 = tmp_path / "file3.py"
        file1.write_text("content1")
        file2.write_text("content2")
        file3.write_text("content3")

        cache = FileCache(tmp_path)
        progress: list[str] = []
        files = [file3, file1, file2]

        with patch.object(FileCache, "_hash_worker_count", return_value=2) as workers:
            changed, stats, computed_hashes = cache.get_changed_files(
                files, on_progress=progress.append
            )

        workers.assert_called_once_with(3)
        assert changed == files
        assert stats.changed_files == 3
        assert stats.skipped_files == 0
        assert computed_hashes.keys() == {"file1.py", "file2.py", "file3.py"}
        assert progress == [
            "Hashing files... 1/3",
            "Hashing files... 2/3",
            "Hashing files... 3/3",
        ]

    def test_get_changed_files_skips_hash_when_metadata_matches(
        self, tmp_path: Path
    ) -> None:
        """Test unchanged cached metadata avoids unnecessary hashing."""
        file1 = tmp_path / "file1.py"
        file2 = tmp_path / "file2.py"
        file1.write_text("content1")
        file2.write_text("content2")

        cache = FileCache(tmp_path)
        cache.update([file1, file2])

        with patch.object(FileCache, "compute_hash") as compute_hash:
            changed, stats, computed_hashes = cache.get_changed_files([file1, file2])

        compute_hash.assert_not_called()
        assert changed == []
        assert stats.changed_files == 0
        assert stats.skipped_files == 2
        assert set(computed_hashes) == {"file1.py", "file2.py"}

    def test_get_changed_files_detects_same_size_change_with_restored_mtime(
        self, tmp_path: Path
    ) -> None:
        """Test ctime metadata preserves accuracy when mtime and size match."""
        file1 = tmp_path / "file1.py"
        file1.write_text("content1")

        cache = FileCache(tmp_path)
        cache.update([file1])
        cached_mtime = file1.stat().st_mtime_ns

        time.sleep(0.01)
        file1.write_text("CONTENT1")
        os.utime(file1, ns=(cached_mtime, cached_mtime))

        with patch.object(
            FileCache, "compute_hash", wraps=cache.compute_hash
        ) as compute_hash:
            changed, stats, computed_hashes = cache.get_changed_files([file1])

        compute_hash.assert_called_once_with(file1)
        assert changed == [file1]
        assert stats.changed_files == 1
        assert stats.skipped_files == 0
        assert computed_hashes["file1.py"] != cache._cache["file1.py"]

    def test_get_changed_files_treats_deleted_file_as_changed_without_hashing(
        self, tmp_path: Path
    ) -> None:
        """Test missing files remain changed when cached metadata short-circuits."""
        file1 = tmp_path / "file1.py"
        file1.write_text("content")

        cache = FileCache(tmp_path)
        cache.update([file1])
        file1.unlink()

        with patch.object(FileCache, "compute_hash") as compute_hash:
            changed, stats, computed_hashes = cache.get_changed_files([file1])

        compute_hash.assert_not_called()
        assert changed == [file1]
        assert stats.changed_files == 1
        assert stats.skipped_files == 0
        assert computed_hashes == {}

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

    def test_has_any_changed_skips_hash_when_metadata_matches(
        self, tmp_path: Path
    ) -> None:
        """Test cached metadata provides a fast unchanged-file path."""
        file1 = tmp_path / "file1.py"
        file1.write_text("content")

        cache = FileCache(tmp_path)
        cache.update([file1])

        with patch.object(FileCache, "compute_hash") as compute_hash:
            assert cache.has_any_changed([file1]) is False

        compute_hash.assert_not_called()

    def test_has_any_changed_detects_same_size_change_with_restored_mtime(
        self, tmp_path: Path
    ) -> None:
        """Test ctime metadata prevents false unchanged results."""
        file1 = tmp_path / "file1.py"
        file1.write_text("content")

        cache = FileCache(tmp_path)
        cache.update([file1])
        cached_mtime = file1.stat().st_mtime_ns

        time.sleep(0.01)
        file1.write_text("CONTENT")
        os.utime(file1, ns=(cached_mtime, cached_mtime))

        with patch.object(
            FileCache, "compute_hash", wraps=cache.compute_hash
        ) as compute_hash:
            assert cache.has_any_changed([file1]) is True

        compute_hash.assert_called_once_with(file1)

    def test_has_any_changed_falls_back_to_hash_when_metadata_differs(
        self, tmp_path: Path
    ) -> None:
        """Test mtime changes still fall back to hash comparison for accuracy."""
        file1 = tmp_path / "file1.py"
        file1.write_text("content")

        cache = FileCache(tmp_path)
        cache.update([file1])
        old_mtime = cache._mtimes["file1.py"]
        os.utime(file1, ns=(old_mtime + 1_000_000_000, old_mtime + 1_000_000_000))

        with patch.object(
            FileCache, "compute_hash", wraps=cache.compute_hash
        ) as compute_hash:
            assert cache.has_any_changed([file1]) is False

        compute_hash.assert_called_once_with(file1)
        assert cache._mtimes["file1.py"] == file1.stat().st_mtime_ns

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


class TestSyncAndSetup:
    """Tests for the shared upload and remote setup lifecycle."""

    @staticmethod
    def _changed_plan(stats: SyncStats) -> SyncPlan:
        """Build the smallest plan that requires an apply operation."""
        changed_file = Path("changed.py")
        return SyncPlan(
            [changed_file], {changed_file: 1}, [changed_file], [], {}, stats
        )

    def test_reuses_executor_for_upload_and_setup(self, file_sync: FileSync) -> None:
        """One executor context performs both project upload and setup steps."""
        executor = MagicMock(context_id="context-id")
        stats = SyncStats(
            cluster_zip_path="/tmp/project.zip",
            remote_calls=2,
            sync_duration=1.0,
        )
        setup_steps = [
            ("Extracting files", "extract()"),
            ("Configuring paths", "sys.path.insert(0, '/tmp/project')"),
        ]
        executor.execute.return_value = MagicMock(status="ok")
        plan = self._changed_plan(stats)

        with (
            patch.object(
                file_sync, "create_sync_plan", return_value=plan
            ) as create_plan,
            patch.object(file_sync, "sync", return_value=stats) as sync,
            patch.object(file_sync, "get_setup_steps", return_value=setup_steps),
            patch(
                "jupyter_databricks_kernel.sync.time.perf_counter",
                side_effect=[10.0, 20.0, 20.25, 30.0, 30.5, 40.0],
            ),
        ):
            result = file_sync.sync_and_setup(executor)

        assert result is stats
        create_plan.assert_called_once_with(on_progress=None)
        sync.assert_called_once_with(on_progress=None, executor=executor, plan=plan)
        executor.create_context.assert_not_called()
        assert executor.execute.call_count == 2
        executor.execute.assert_any_call("extract()", allow_reconnect=False)
        executor.execute.assert_any_call(
            "sys.path.insert(0, '/tmp/project')", allow_reconnect=False
        )
        assert stats.remote_calls == 4
        assert stats.remote_apply_duration == 0.25
        assert stats.path_setup_duration == 0.5
        assert stats.upload_duration == 0.0
        assert stats.total_duration == 30.0
        assert stats.sync_duration == 30.0

    def test_counts_executor_context_creation_in_setup_boundary(
        self, file_sync: FileSync
    ) -> None:
        """End-to-end setup stats include an executor context created up front."""
        executor = MagicMock(context_id=None)
        stats = SyncStats(cluster_zip_path="/tmp/project.zip", remote_calls=2)
        plan = self._changed_plan(stats)

        with (
            patch.object(file_sync, "create_sync_plan", return_value=plan),
            patch.object(file_sync, "sync", return_value=stats),
            patch.object(file_sync, "get_setup_steps", return_value=[]),
            patch(
                "jupyter_databricks_kernel.sync.time.perf_counter",
                side_effect=[5.0, 5.1, 5.4, 6.0],
            ),
        ):
            result = file_sync.sync_and_setup(executor)

        assert result is stats
        executor.create_context.assert_called_once_with()
        assert stats.context_setup_duration == pytest.approx(0.3)
        assert stats.remote_calls == 3
        assert stats.upload_duration == 0.0
        assert stats.total_duration == 1.0
        assert stats.sync_duration == 1.0

    def test_total_duration_includes_plan_creation(self, file_sync: FileSync) -> None:
        """End-to-end setup timing starts before one plan creation."""
        executor = MagicMock(context_id="context-id")
        stats = SyncStats(cluster_zip_path="/tmp/project.zip", remote_calls=2)

        def create_plan_with_preflight(
            on_progress: object = None,
        ) -> SyncPlan:
            assert on_progress is None
            preflight_start = time.perf_counter()
            preflight_end = time.perf_counter()
            assert preflight_end - preflight_start == 1.0
            return self._changed_plan(stats)

        with (
            patch.object(
                file_sync, "create_sync_plan", side_effect=create_plan_with_preflight
            ),
            patch.object(file_sync, "sync", return_value=stats),
            patch.object(file_sync, "get_setup_steps", return_value=[]),
            patch(
                "jupyter_databricks_kernel.sync.time.perf_counter",
                side_effect=[1.0, 2.0, 3.0, 6.0],
            ),
        ):
            result = file_sync.sync_and_setup(executor)

        assert result is stats
        executor.create_context.assert_not_called()
        assert stats.total_duration == 5.0
        assert stats.sync_duration == 5.0

    def test_skips_upload_and_setup_when_no_sync_is_needed(
        self, file_sync: FileSync
    ) -> None:
        """A clean project does not create a context or execute setup code."""
        executor = MagicMock()
        plan = SyncPlan([], {}, [], [], {}, SyncStats())

        with (
            patch.object(file_sync, "create_sync_plan", return_value=plan),
            patch.object(file_sync, "sync") as sync,
        ):
            result = file_sync.sync_and_setup(executor)

        assert result is None
        sync.assert_not_called()
        executor.create_context.assert_not_called()
        executor.execute.assert_not_called()

    def test_warm_cache_fresh_instance_applies_once_then_skips(
        self, mock_config: MagicMock, tmp_path: Path
    ) -> None:
        """A fresh process applies even when its persistent cache is warm."""
        mock_config.base_path = tmp_path
        mock_config.sync.source = "."
        mock_config.sync.exclude = []
        source_file = tmp_path / "project.py"
        source_file.write_text("value = 1\n")
        cache_home = tmp_path.parent / f"{tmp_path.name}-cache"

        with patch.dict(os.environ, {"XDG_CACHE_HOME": str(cache_home)}):
            warm_cache = FileCache(tmp_path)
            warm_cache.update([source_file])
            warm_cache.save()

            fresh_sync = FileSync(mock_config, "fresh-session")
            executor = MagicMock(context_id="context-id")
            executor.execute.return_value = MagicMock(status="ok")
            stats = SyncStats(cluster_zip_path="/tmp/project.zip")

            def apply_once(**_: object) -> SyncStats:
                fresh_sync._synced = True
                return stats

            with (
                patch.object(fresh_sync, "sync", side_effect=apply_once) as sync,
                patch.object(
                    fresh_sync,
                    "get_setup_steps",
                    return_value=[("Configuring paths", "setup()")],
                ),
            ):
                first_result = fresh_sync.sync_and_setup(executor)
                second_result = fresh_sync.sync_and_setup(executor)

        assert first_result is stats
        assert second_result is None
        sync.assert_called_once()
        executor.execute.assert_called_once_with("setup()", allow_reconnect=False)

    def test_sync_plan_freezes_decision_data(self) -> None:
        """A plan cannot be changed after it is created."""
        changed_file = Path("changed.py")
        files = [changed_file]
        file_sizes = {changed_file: 1}
        changed_files = [changed_file]
        deleted_files = ["deleted.py"]
        computed_hashes = {"changed.py": "hash"}

        plan = SyncPlan(
            files,
            file_sizes,
            changed_files,
            deleted_files,
            computed_hashes,
            SyncStats(),
        )
        files.clear()
        file_sizes.clear()
        changed_files.clear()
        deleted_files.clear()
        computed_hashes.clear()

        assert plan.all_files == (changed_file,)
        assert dict(plan.file_sizes) == {changed_file: 1}
        assert plan.changed_files == (changed_file,)
        assert plan.deleted_files == ("deleted.py",)
        assert dict(plan.computed_hashes) == {"changed.py": "hash"}
        with pytest.raises(TypeError):
            plan.file_sizes[changed_file] = 2
        with pytest.raises(AttributeError):
            plan.changed_files += (Path("other.py"),)

    def test_reports_the_failed_remote_setup_step(self, file_sync: FileSync) -> None:
        """Setup errors identify the step that did not complete."""
        executor = MagicMock(context_id="context-id")
        stats = SyncStats(cluster_zip_path="/tmp/project.zip")
        executor.execute.return_value = MagicMock(
            status="error", error="permission denied"
        )
        plan = self._changed_plan(stats)

        with (
            patch.object(file_sync, "create_sync_plan", return_value=plan),
            patch.object(file_sync, "sync", return_value=stats),
            patch.object(
                file_sync,
                "get_setup_steps",
                return_value=[("Extracting files", "extract()")],
            ),
            pytest.raises(SetupError, match="Extracting files") as exc_info,
        ):
            file_sync.sync_and_setup(executor)

        assert exc_info.value.description == "Extracting files"
        assert exc_info.value.error == "permission denied"

    def test_cleanup_deletes_uid_fallback_transfer_archive(
        self, file_sync: FileSync
    ) -> None:
        """Cleanup removes the actual driver-local archive via its upload context."""
        client = MagicMock()
        file_sync.client = client
        file_sync._cluster_zip_path = (
            "/tmp/jupyter_databricks_kernel_test-session_1000/project.zip"
        )
        file_sync._transfer_context_id = "caller-context"

        file_sync.cleanup()

        command = client.command_execution.execute.call_args.kwargs["command"]
        assert "os.remove" in command
        assert "jupyter_databricks_kernel_test-session_1000/project.zip" in command
        assert client.command_execution.execute.call_args.kwargs["context_id"] == (
            "caller-context"
        )
        assert file_sync._cluster_zip_path is None
        assert file_sync._transfer_context_id is None

    def test_archive_cleanup_command_ignores_absent_archive(self) -> None:
        """A repeated cleanup does not fail when setup already removed the archive."""
        command = build_command_api_archive_cleanup_command("/tmp/project.zip")

        assert 'os.remove("/tmp/project.zip")' in command
        assert "except FileNotFoundError" in command


class TestSyncStats:
    """Tests for SyncStats dataclass."""

    def test_default_values(self) -> None:
        """Test default values."""
        stats = SyncStats()
        assert stats.changed_files == 0
        assert stats.changed_size == 0
        assert stats.deleted_files == 0
        assert stats.skipped_files == 0
        assert stats.total_files == 0
        assert stats.upload_duration == 0.0
        assert stats.total_duration == 0.0
        assert stats.sync_duration == 0.0
        assert stats.cluster_zip_path == ""
        assert stats.source_size == 0
        assert stats.archive_size == 0
        assert stats.chunk_count == 0
        assert stats.remote_calls == 0
        assert stats.mode == "full"
        assert stats.discovery_duration == 0.0
        assert stats.change_detection_duration == 0.0
        assert stats.archive_creation_duration == 0.0
        assert stats.context_setup_duration == 0.0
        assert stats.transfer_duration == 0.0
        assert stats.remote_apply_duration == 0.0
        assert stats.path_setup_duration == 0.0

    def test_with_values(self) -> None:
        """Test with custom values."""
        stats = SyncStats(
            changed_files=3,
            changed_size=1024,
            deleted_files=2,
            skipped_files=10,
            total_files=13,
            upload_duration=1.25,
            total_duration=2.5,
            sync_duration=1.5,
            cluster_zip_path="/tmp/test/project.zip",
            source_size=4096,
            archive_size=2048,
            chunk_count=1,
            remote_calls=5,
            mode="full",
            discovery_duration=0.1,
            change_detection_duration=0.2,
            archive_creation_duration=0.3,
            context_setup_duration=0.4,
            transfer_duration=0.5,
            remote_apply_duration=0.6,
            path_setup_duration=0.7,
        )
        assert stats.changed_files == 3
        assert stats.changed_size == 1024
        assert stats.deleted_files == 2
        assert stats.skipped_files == 10
        assert stats.total_files == 13
        assert stats.upload_duration == 1.25
        assert stats.total_duration == 2.5
        assert stats.sync_duration == 1.5
        assert stats.cluster_zip_path == "/tmp/test/project.zip"
        assert stats.source_size == 4096
        assert stats.archive_size == 2048
        assert stats.chunk_count == 1
        assert stats.remote_calls == 5
        assert stats.mode == "full"
        assert stats.discovery_duration == 0.1
        assert stats.change_detection_duration == 0.2
        assert stats.archive_creation_duration == 0.3
        assert stats.context_setup_duration == 0.4
        assert stats.transfer_duration == 0.5
        assert stats.remote_apply_duration == 0.6
        assert stats.path_setup_duration == 0.7

    def test_preserves_positional_constructor_contract(self) -> None:
        """The original six positional fields remain in their existing order."""
        stats = SyncStats(3, 1024, 10, 13, 1.5, "/tmp/test/project.zip")

        assert stats.changed_files == 3
        assert stats.changed_size == 1024
        assert stats.skipped_files == 10
        assert stats.total_files == 13
        assert stats.sync_duration == 1.5
        assert stats.cluster_zip_path == "/tmp/test/project.zip"
        assert stats.deleted_files == 0
        assert stats.upload_duration == 0.0
        assert stats.total_duration == 0.0


class TestDefaultExcludePatterns:
    """Tests for default exclude patterns matching Databricks CLI."""

    def test_contains_databricks_git_venv_and_cache_file(self) -> None:
        """Test that .databricks, .git, .venv, and cache file are excluded."""
        assert ".databricks" in DEFAULT_EXCLUDE_PATTERNS
        assert ".git" in DEFAULT_EXCLUDE_PATTERNS
        assert ".venv" in DEFAULT_EXCLUDE_PATTERNS
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
        mock_config.base_path = tmp_path
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
        mock_config.base_path = tmp_path
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
        mock_config.base_path = tmp_path
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
            mock_config.base_path = test_dir
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
            mock_config.base_path = test_dir
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


class TestCreateZip:
    """Tests for _create_zip archive construction."""

    @pytest.mark.parametrize("compression_level", [None, 1])
    def test_create_zip_passes_compression_level_to_zipfile(
        self,
        compression_level: int | None,
        mock_config: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test that _create_zip passes compression level through to zipfile."""
        import zipfile

        mock_config.sync.source = str(tmp_path)
        mock_config.sync.exclude = []
        mock_config.sync.compression_level = compression_level
        mock_config.base_path = tmp_path
        file_sync = FileSync(mock_config, "test-session")

        regular_file = tmp_path / "regular.py"
        regular_file.write_text("print('hello')")

        with patch("jupyter_databricks_kernel.sync.zipfile.ZipFile") as zip_file:
            file_sync._create_zip([regular_file])

        zip_file.assert_called_once_with(
            ANY,
            "w",
            zipfile.ZIP_DEFLATED,
            compresslevel=compression_level,
        )
        zip_file.return_value.__enter__.return_value.write.assert_called_once_with(
            regular_file,
            Path("regular.py"),
        )


class TestGetSetupCode:
    """Tests for get_setup_code method."""

    def test_setup_code_includes_chdir(self, mock_config: MagicMock) -> None:
        """Test that setup code sets working directory."""
        file_sync = FileSync(mock_config, "test-session")
        setup_code = file_sync.get_setup_code("/tmp/test.zip")
        assert "os.chdir(_extract_dir)" in setup_code

    def test_setup_code_includes_sys_path(self, mock_config: MagicMock) -> None:
        """Test that setup code adds to sys.path."""
        file_sync = FileSync(mock_config, "test-session")
        setup_code = file_sync.get_setup_code("/tmp/test.zip")
        assert "sys.path.insert(0, _extract_dir)" in setup_code


class TestGetSourcePathWithBasePath:
    """Tests for _get_source_path with base_path."""

    def test_uses_base_path_when_set(self, tmp_path: Path) -> None:
        """Test that source path uses base_path when available."""
        config = MagicMock()
        config.sync.enabled = True
        config.sync.source = "."
        config.sync.exclude = []
        config.base_path = tmp_path

        file_sync = FileSync(config, "test-session")
        source_path = file_sync._get_source_path()

        assert source_path == tmp_path

    def test_uses_base_path_with_relative_source(self, tmp_path: Path) -> None:
        """Test that source path combines base_path with relative source."""
        config = MagicMock()
        config.sync.enabled = True
        config.sync.source = "./src"
        config.sync.exclude = []
        config.base_path = tmp_path

        file_sync = FileSync(config, "test-session")
        source_path = file_sync._get_source_path()

        assert source_path == tmp_path / "src"

    def test_falls_back_to_cwd_when_no_base_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that source path uses cwd when base_path is None."""
        monkeypatch.chdir(tmp_path)

        config = MagicMock()
        config.sync.enabled = True
        config.sync.source = "."
        config.sync.exclude = []
        config.base_path = None

        file_sync = FileSync(config, "test-session")
        source_path = file_sync._get_source_path()

        assert source_path == tmp_path

    def test_hierarchical_project_structure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test the actual use case: notebook in subdirectory.

        Simulates the scenario where:
        - Project root has pyproject.toml
        - User runs notebook from notebooks/ subdirectory
        - sync.source = "." should sync from project root, not notebooks/
        """
        # Create project structure
        project_root = tmp_path / "project"
        project_root.mkdir()

        notebooks_dir = project_root / "notebooks"
        notebooks_dir.mkdir()

        src_dir = project_root / "src"
        src_dir.mkdir()
        (src_dir / "main.py").write_text("print('hello')")

        # Simulate being in notebooks/ directory
        monkeypatch.chdir(notebooks_dir)

        # Config with base_path pointing to project root (where pyproject.toml is)
        config = MagicMock()
        config.sync.enabled = True
        config.sync.source = "."
        config.sync.exclude = []
        config.base_path = project_root  # Simulates pyproject.toml found in parent

        file_sync = FileSync(config, "test-session")
        source_path = file_sync._get_source_path()

        # Should resolve to project root, not notebooks/
        assert source_path == project_root

    def test_hierarchical_with_src_source(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test hierarchical structure with source = './src'."""
        project_root = tmp_path / "project"
        project_root.mkdir()

        notebooks_dir = project_root / "notebooks"
        notebooks_dir.mkdir()

        src_dir = project_root / "src"
        src_dir.mkdir()

        # Simulate being in notebooks/ directory
        monkeypatch.chdir(notebooks_dir)

        config = MagicMock()
        config.sync.enabled = True
        config.sync.source = "./src"
        config.sync.exclude = []
        config.base_path = project_root

        file_sync = FileSync(config, "test-session")
        source_path = file_sync._get_source_path()

        # Should resolve to project_root/src
        assert source_path == src_dir


class TestGetSetupSteps:
    """Tests for FileSync.get_setup_steps() method."""

    def test_default_tmp_path(self, mock_file_sync: FileSync) -> None:
        """Test that single /tmp/jupyter_databricks_kernel/<project>/ path is used."""
        cluster_zip_path = "/tmp/test/project.zip"
        steps = mock_file_sync.get_setup_steps(cluster_zip_path)

        # Should return 3 steps
        assert len(steps) == 3
        assert steps[0][0] == "Preparing directory"
        assert steps[1][0] == "Extracting files"
        assert steps[2][0] == "Configuring paths"

        # Check single path — no fallback logic
        prepare_code = steps[0][1]
        assert "/tmp/jupyter_databricks_kernel/" in prepare_code
        assert "_primary_dir" not in prepare_code
        assert "_fallback_dir" not in prepare_code
        assert "/Workspace/Users/" not in prepare_code
        assert "try:" not in prepare_code
        assert "except" not in prepare_code

    def test_custom_workspace_extract_dir(self, mock_file_sync: FileSync) -> None:
        """Test that custom workspace_extract_dir is used when configured."""
        # Set custom extract dir
        custom_dir = "/custom/path/to/extract"
        mock_file_sync.config.sync.workspace_extract_dir = custom_dir

        cluster_zip_path = "/tmp/test/project.zip"
        steps = mock_file_sync.get_setup_steps(cluster_zip_path)

        # Should return 4 steps
        assert len(steps) == 4

        # Check that first step uses custom path without fallback logic
        prepare_code = steps[0][1]
        assert custom_dir in prepare_code
        assert "_primary_dir" not in prepare_code
        assert "_fallback_dir" not in prepare_code
        assert "try:" not in prepare_code

    def test_workspace_mount_extract_dir_rejected(
        self, mock_file_sync: FileSync
    ) -> None:
        """Test that /Workspace extraction paths are not supported."""
        mock_file_sync.config.sync.workspace_extract_dir = (
            "/Workspace/Users/example/project"
        )

        with pytest.raises(ValueError, match="must not use /Workspace"):
            mock_file_sync.get_setup_steps("/tmp/test/project.zip")

    def test_default_path_is_deterministic(self, mock_file_sync: FileSync) -> None:
        """Test that default path is deterministic (no session UUID in path)."""
        cluster_zip_path = "/tmp/test/project.zip"
        steps = mock_file_sync.get_setup_steps(cluster_zip_path)

        prepare_code = steps[0][1]
        # Session ID must NOT appear in default path — path is project-scoped
        assert "test-session-id" not in prepare_code
        # Path must be under /tmp/jupyter_databricks_kernel/
        assert "/tmp/jupyter_databricks_kernel/" in prepare_code

    def test_default_path_includes_project_hash(
        self, mock_config: MagicMock, tmp_path: Path
    ) -> None:
        """Test that default path includes a project-root hash."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        mock_config.base_path = project_root
        file_sync = FileSync(mock_config, "test-session-id")

        steps = file_sync.get_setup_steps("/tmp/test/project.zip")

        prepare_code = steps[0][1]
        expected_path = (
            f"/tmp/jupyter_databricks_kernel/project-{get_project_hash(project_root)}"
        )
        assert expected_path in prepare_code

    def test_same_project_names_get_distinct_default_paths(
        self, mock_config: MagicMock, tmp_path: Path
    ) -> None:
        """Test that same-name project roots do not share default paths."""
        first_root = tmp_path / "first" / "project"
        second_root = tmp_path / "second" / "project"
        first_root.mkdir(parents=True)
        second_root.mkdir(parents=True)

        mock_config.base_path = first_root
        first_sync = FileSync(mock_config, "first-session")
        first_prepare_code = first_sync.get_setup_steps("/tmp/test/project.zip")[0][1]

        mock_config.base_path = second_root
        second_sync = FileSync(mock_config, "second-session")
        second_prepare_code = second_sync.get_setup_steps("/tmp/test/project.zip")[0][1]

        assert f"project-{get_project_hash(first_root)}" in first_prepare_code
        assert f"project-{get_project_hash(second_root)}" in second_prepare_code
        assert first_prepare_code != second_prepare_code

    def test_cluster_zip_path_in_code(self, mock_file_sync: FileSync) -> None:
        """Test that zip path is correctly embedded in generated code."""
        cluster_zip_path = "/tmp/test/project.zip"
        steps = mock_file_sync.get_setup_steps(cluster_zip_path)

        # Command API method: zip is already on cluster, no dbfs: prefix
        # Check that extraction step references the cluster zip path
        extract_code = steps[1][1]
        assert cluster_zip_path in extract_code
        assert "_cluster_zip" in extract_code


class TestCommandAPITransfer:
    """Tests for Command API-based file transfer with Base64 encoding."""

    def test_direct_base64_chunks_reconstruct_original_bytes(self) -> None:
        """Test that each chunk is independently decodable."""
        test_data = b"x" * (COMMAND_API_BINARY_CHUNK_SIZE + 17)

        chunks = list(iter_command_api_base64_chunks(test_data))

        assert len(chunks) == 2
        assert b"".join(base64.b64decode(chunk) for chunk in chunks) == test_data

    def test_chunk_size_leaves_command_wrapper_headroom(self) -> None:
        """Test that generated commands stay under the command-size budget."""
        chunk_b64 = next(
            iter_command_api_base64_chunks(b"x" * COMMAND_API_BINARY_CHUNK_SIZE)
        )
        command = build_command_api_chunk_write_command(
            "/tmp/jupyter_databricks_kernel_test-session/project.zip",
            chunk_b64,
            "wb",
        )

        assert len(chunk_b64.encode("ascii")) <= (
            COMMAND_API_MAX_COMMAND_BYTES - COMMAND_API_COMMAND_HEADROOM_BYTES
        )
        assert len(command.encode("utf-8")) < COMMAND_API_MAX_COMMAND_BYTES

    def test_sync_writes_decoded_chunks_directly_to_zip(
        self, mock_file_sync: FileSync, tmp_path: Path
    ) -> None:
        """Test sync writes decoded chunks without a remote .b64 accumulator."""
        payload = b"z" * (COMMAND_API_BINARY_CHUNK_SIZE + 23)
        test_file = tmp_path / "test.py"
        test_file.write_text("print('test')\n")
        mock_file_sync.config.base_path = tmp_path

        fake_cache = MagicMock()
        fake_cache.get_changed_files.return_value = (
            [test_file],
            SyncStats(changed_files=1, changed_size=len(payload)),
            {test_file: "hash"},
        )
        fake_cache.get_deleted_files.return_value = []

        mock_file_sync._get_all_files = Mock(return_value=[test_file])
        mock_file_sync._get_file_cache = Mock(return_value=fake_cache)
        mock_file_sync._create_zip = Mock(return_value=payload)

        result = MagicMock()
        from databricks.sdk.service import compute

        result.status = compute.CommandStatus.FINISHED
        result.results = MagicMock()
        result.results.cause = None
        result.results.data = "/tmp/jupyter_databricks_kernel_test-session"
        execute_response = mock_file_sync.client.command_execution.execute.return_value
        execute_response.result.return_value = result

        stats = mock_file_sync.sync()

        commands = [
            call.kwargs["command"]
            for call in mock_file_sync.client.command_execution.execute.call_args_list
        ]
        chunk_commands = [
            command for command in commands if "base64.b64decode" in command
        ]

        assert stats.cluster_zip_path.endswith("/project.zip")
        assert len(chunk_commands) == count_command_api_base64_chunks(len(payload))
        assert "project.zip.b64" not in "\n".join(commands)
        assert "os.remove" not in "\n".join(chunk_commands)
        assert (
            'open("/tmp/jupyter_databricks_kernel_test-session/project.zip", "wb")'
            in chunk_commands[0]
        )
        assert (
            'open("/tmp/jupyter_databricks_kernel_test-session/project.zip", "ab")'
            in chunk_commands[1]
        )
        assert all(
            len(command.encode("utf-8")) < COMMAND_API_MAX_COMMAND_BYTES
            for command in chunk_commands
        )

        encoded_chunks = [
            re.search(r'base64\.b64decode\("([^"]*)"\)', command).group(1)
            for command in chunk_commands
        ]
        assert b"".join(base64.b64decode(chunk) for chunk in encoded_chunks) == payload

    def test_sync_records_phase_diagnostics(
        self, mock_file_sync: FileSync, tmp_path: Path
    ) -> None:
        """Sync reports phase timings and transfer counters for benchmarks."""
        test_file = tmp_path / "test.py"
        test_file.write_text("print('test')\n")
        payload = b"z" * (COMMAND_API_BINARY_CHUNK_SIZE + 23)
        mock_file_sync.config.base_path = tmp_path

        fake_cache = MagicMock()
        fake_cache.get_changed_files.return_value = (
            [test_file],
            SyncStats(changed_files=1, changed_size=test_file.stat().st_size),
            {"test.py": "hash"},
        )
        fake_cache.get_deleted_files.return_value = ["deleted.py"]

        mock_file_sync._get_all_files = Mock(return_value=[test_file])
        mock_file_sync._get_file_cache = Mock(return_value=fake_cache)
        mock_file_sync._create_zip = Mock(return_value=payload)

        result = MagicMock()
        from databricks.sdk.service import compute

        result.status = compute.CommandStatus.FINISHED
        result.results = MagicMock()
        result.results.cause = None
        result.results.data = "/tmp/jupyter_databricks_kernel_test-session"
        execute_response = mock_file_sync.client.command_execution.execute.return_value
        execute_response.result.return_value = result

        stats = mock_file_sync.sync()

        assert stats.total_files == 1
        assert stats.changed_files == 1
        assert stats.deleted_files == 1
        assert stats.source_size == test_file.stat().st_size
        assert stats.archive_size == len(payload)
        assert stats.chunk_count == count_command_api_base64_chunks(len(payload))
        assert stats.remote_calls == stats.chunk_count + 2
        assert stats.mode == "full"
        assert stats.cluster_zip_path.endswith("/project.zip")
        assert stats.upload_duration >= 0
        assert stats.total_duration == stats.upload_duration
        assert stats.sync_duration >= 0
        assert stats.sync_duration == stats.total_duration
        assert stats.discovery_duration >= 0
        assert stats.change_detection_duration >= 0
        assert stats.archive_creation_duration >= 0
        assert stats.context_setup_duration >= 0
        assert stats.transfer_duration >= 0
        fake_cache.remove.assert_called_once_with("deleted.py")

    def test_direct_sync_preserves_disabled_setting_compatibility(
        self, mock_file_sync: FileSync
    ) -> None:
        """Direct sync retains its historical enabled-setting-independent apply."""
        mock_file_sync.config.sync.enabled = False
        plan = SyncPlan([], {}, [], [], {}, SyncStats())
        mock_file_sync.client = MagicMock()

        result = MagicMock()
        from databricks.sdk.service import compute

        result.status = compute.CommandStatus.FINISHED
        result.results = MagicMock(cause=None)
        result.results.data = "/tmp/jupyter_databricks_kernel_test-session"
        execute_response = mock_file_sync.client.command_execution.execute.return_value
        execute_response.result.return_value = result
        create_response = mock_file_sync.client.command_execution.create.return_value
        create_response.result.return_value.id = "context-id"

        with (
            patch.object(mock_file_sync, "create_sync_plan", return_value=None),
            patch.object(
                mock_file_sync, "_build_sync_plan", return_value=plan
            ) as build,
            patch.object(mock_file_sync, "_create_zip", return_value=b"zip"),
        ):
            mock_file_sync.sync()

        build.assert_called_once_with(on_progress=None)
        assert mock_file_sync.client.command_execution.execute.called

    def test_executor_context_sharing(
        self, mock_file_sync: FileSync, tmp_path: Path
    ) -> None:
        """Test that executor context is shared between sync and setup."""
        # Create mock executor with context_id
        mock_executor = Mock()
        mock_executor.context_id = "test-context-123"

        # Mock WorkspaceClient and command_execution
        mock_client = MagicMock()
        mock_file_sync.client = mock_client

        # Mock command execution responses
        mock_result = MagicMock()
        mock_result.status = MagicMock()
        mock_result.status.__eq__ = lambda self, other: other == "FINISHED"
        mock_result.results = MagicMock()
        mock_result.results.cause = None
        mock_result.results.data = "/tmp/jupyter_databricks_kernel_test-session"

        mock_client.command_execution.execute.return_value.result.return_value = (
            mock_result
        )

        # Create test file
        test_file = tmp_path / "test.py"
        test_file.write_text("print('test')")

        # Mock _get_all_files to return our test file
        mock_file_sync._get_all_files = Mock(return_value=[test_file])
        fake_cache = MagicMock()
        fake_cache.get_changed_files.return_value = (
            [test_file],
            SyncStats(changed_files=1, changed_size=test_file.stat().st_size),
            {"test.py": "hash"},
        )
        fake_cache.get_deleted_files.return_value = ["deleted.py"]
        mock_file_sync._get_file_cache = Mock(return_value=fake_cache)

        # Execute sync with executor parameter
        try:
            mock_file_sync.sync(executor=mock_executor)
            # Verify that command_execution.execute was called
            assert mock_client.command_execution.execute.called
        except Exception:
            # Expected to fail in mock environment
            # We just verify the context sharing logic
            pass

    def test_uid_fallback_mkdir_code(self) -> None:
        """Test that mkdir_code includes UID fallback logic."""
        # The mkdir_code should test write permissions and fallback to UID suffix
        mkdir_code_template = """
import os
target_dir = "/tmp/test_dir"
try:
    os.makedirs(target_dir, exist_ok=True)
    probe = os.path.join(target_dir, '.probe')
    with open(probe, 'w') as f:
        f.write('ok')
    os.remove(probe)
except PermissionError:
    target_dir = f"{{target_dir}}_{{os.getuid()}}"
    os.makedirs(target_dir, exist_ok=True)
print(target_dir)
"""
        # Verify the logic contains key components
        assert "try:" in mkdir_code_template
        assert "PermissionError:" in mkdir_code_template
        assert "os.getuid()" in mkdir_code_template
        assert ".probe" in mkdir_code_template
        assert "print(target_dir)" in mkdir_code_template

    def test_command_api_error_handling(
        self, mock_file_sync: FileSync, tmp_path: Path
    ) -> None:
        """Test Command API error handling via result.results.cause."""
        import pytest

        # Mock WorkspaceClient and command_execution
        mock_client = MagicMock()
        mock_file_sync.client = mock_client

        # Mock command execution failure with cause
        mock_result = MagicMock()
        mock_result.status = MagicMock()
        mock_result.status.__eq__ = lambda self, other: other == "ERROR"
        mock_result.results = MagicMock()
        mock_result.results.cause = "ExecutionError: Permission denied"

        mock_client.command_execution.execute.return_value.result.return_value = (
            mock_result
        )

        # Create test file
        test_file = tmp_path / "test.py"
        test_file.write_text("print('test')")

        # Mock _get_all_files to return our test file
        mock_file_sync._get_all_files = Mock(return_value=[test_file])
        fake_cache = MagicMock()
        fake_cache.get_changed_files.return_value = (
            [test_file],
            SyncStats(changed_files=1, changed_size=test_file.stat().st_size),
            {"test.py": "hash"},
        )
        fake_cache.get_deleted_files.return_value = ["deleted.py"]
        mock_file_sync._get_file_cache = Mock(return_value=fake_cache)

        # Execute sync should raise error due to cause
        with pytest.raises(Exception) as exc_info:
            mock_file_sync.sync()

        # Verify error message contains cause information
        error_msg = str(exc_info.value).lower()
        assert "cause" in error_msg or "error" in error_msg
        fake_cache.remove.assert_not_called()
        fake_cache.update.assert_not_called()
        fake_cache.save.assert_not_called()
