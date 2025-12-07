"""File synchronization to Databricks DBFS.

This module implements file synchronization matching Databricks CLI behavior.
It respects .gitignore files and always excludes the .databricks directory.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pathspec
from databricks.sdk import WorkspaceClient

if TYPE_CHECKING:
    from .config import Config

logger = logging.getLogger(__name__)

CACHE_FILE_NAME = ".databricks-kernel-cache.json"
CACHE_VERSION = 1

# Default patterns that are always excluded, matching Databricks CLI behavior.
# See: https://github.com/databricks/cli/blob/main/libs/git/view.go
DEFAULT_EXCLUDE_PATTERNS = [
    ".databricks",
    CACHE_FILE_NAME,  # Exclude cache file to prevent infinite sync loop
]


class FileSizeError(Exception):
    """Exception raised when file size limits are exceeded."""

    pass


@dataclass
class SyncStats:
    """Statistics for file synchronization."""

    changed_files: int = 0
    changed_size: int = 0
    skipped_files: int = 0
    total_files: int = 0
    sync_duration: float = 0.0
    dbfs_path: str = ""


@dataclass
class FileCache:
    """MD5 hash-based file cache for change detection."""

    source_path: Path
    _cache: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Load cache from file after initialization."""
        self._load()

    @property
    def cache_path(self) -> Path:
        """Get the cache file path."""
        return self.source_path / CACHE_FILE_NAME

    def _load(self) -> None:
        """Load cache from file. Falls back to empty cache on error."""
        if not self.cache_path.exists():
            return

        try:
            with open(self.cache_path) as f:
                data: dict[str, Any] = json.load(f)

            # Validate version
            if data.get("version") != CACHE_VERSION:
                logger.warning("Cache version mismatch, resetting cache")
                self._cache = {}
                return

            self._cache = data.get("files", {})
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load cache, resetting: %s", e)
            self._cache = {}

    def save(self) -> None:
        """Save cache to file."""
        try:
            data = {
                "version": CACHE_VERSION,
                "files": self._cache,
            }
            with open(self.cache_path, "w") as f:
                json.dump(data, f, indent=2)
        except OSError as e:
            logger.warning("Failed to save cache: %s", e)

    @staticmethod
    def compute_hash(file_path: Path) -> str:
        """Compute MD5 hash of a file.

        Uses hashlib.file_digest() for memory-efficient chunked reading,
        which prevents memory pressure when processing large files.

        Args:
            file_path: Path to the file.

        Returns:
            MD5 hash as hexadecimal string.
        """
        # MD5 is used for change detection only, not for security purposes.
        # Pass a callable to set usedforsecurity=False for FIPS compliance.
        with open(file_path, "rb") as f:
            return hashlib.file_digest(
                f, lambda: hashlib.md5(usedforsecurity=False)
            ).hexdigest()

    def get_changed_files(
        self, files: list[Path], file_sizes: dict[Path, int] | None = None
    ) -> tuple[list[Path], SyncStats, dict[str, str]]:
        """Get list of changed files and sync statistics.

        Args:
            files: List of file paths to check.
            file_sizes: Optional dict of pre-computed file sizes (path -> size).
                If provided, sizes are reused instead of calling stat() again.

        Returns:
            Tuple of (changed files list, sync statistics, computed hashes).
            The computed hashes dict maps relative paths to their MD5 hashes,
            which can be passed to update() to avoid recomputing.
        """
        changed: list[Path] = []
        stats = SyncStats(total_files=len(files))
        computed_hashes: dict[str, str] = {}

        for file_path in files:
            try:
                rel_path = str(file_path.relative_to(self.source_path))
                current_hash = self.compute_hash(file_path)
                computed_hashes[rel_path] = current_hash
                cached_hash = self._cache.get(rel_path)

                if current_hash != cached_hash:
                    changed.append(file_path)
                    stats.changed_files += 1
                    # Reuse pre-computed size if available
                    if file_sizes and file_path in file_sizes:
                        stats.changed_size += file_sizes[file_path]
                    else:
                        stats.changed_size += file_path.stat().st_size
                else:
                    stats.skipped_files += 1
            except OSError:
                # File read error, treat as changed
                changed.append(file_path)
                stats.changed_files += 1

        return changed, stats, computed_hashes

    def update(
        self, files: list[Path], computed_hashes: dict[str, str] | None = None
    ) -> None:
        """Update cache with current file hashes.

        Args:
            files: List of file paths to update.
            computed_hashes: Optional dict of pre-computed hashes (rel_path -> hash).
                If provided, hashes are reused instead of recomputing.
        """
        for file_path in files:
            try:
                rel_path = str(file_path.relative_to(self.source_path))
                if computed_hashes and rel_path in computed_hashes:
                    self._cache[rel_path] = computed_hashes[rel_path]
                else:
                    self._cache[rel_path] = self.compute_hash(file_path)
            except OSError:
                pass  # Skip files that can't be read

    def clear(self) -> None:
        """Clear the cache."""
        self._cache = {}

    def get_deleted_files(self, current_files: list[Path]) -> list[str]:
        """Get list of files that exist in cache but not in current files.

        Args:
            current_files: List of currently existing file paths.

        Returns:
            List of relative paths of deleted files.
        """
        current_rel_paths = {
            str(f.relative_to(self.source_path)) for f in current_files
        }
        return [
            rel_path
            for rel_path in self._cache.keys()
            if rel_path not in current_rel_paths
        ]

    def remove(self, rel_path: str) -> None:
        """Remove a file from the cache.

        Args:
            rel_path: Relative path of the file to remove.
        """
        self._cache.pop(rel_path, None)

    def has_any_changed(self, files: list[Path]) -> bool:
        """Check if any file has changed, with early return on first change.

        This is more efficient than get_changed_files() when you only need
        to know if sync is needed, as it stops at the first changed file.

        Args:
            files: List of file paths to check.

        Returns:
            True if any file has changed, False otherwise.
        """
        for file_path in files:
            try:
                rel_path = str(file_path.relative_to(self.source_path))
                current_hash = self.compute_hash(file_path)
                cached_hash = self._cache.get(rel_path)
                if current_hash != cached_hash:
                    return True
            except OSError:
                # File read error, treat as changed
                return True
        return False


class FileSync:
    """Synchronizes local files to Databricks DBFS.

    This class implements file synchronization matching Databricks CLI behavior:
    - Respects .gitignore files in the source directory
    - Always excludes .databricks directory

    The exclusion logic follows this priority:
    1. .databricks directory (always excluded)
    2. .gitignore patterns (if present)
    3. User-configured exclude patterns from config file
    """

    def __init__(self, config: Config, session_id: str) -> None:
        """Initialize file sync.

        Args:
            config: Kernel configuration.
            session_id: Session identifier for DBFS paths.
        """
        self.config = config
        self.client: WorkspaceClient | None = None
        self.session_id = session_id
        self._synced = False
        self._user_name: str | None = None
        self._pathspec: pathspec.PathSpec | None = None
        self._pathspec_mtime: float = 0.0
        self._file_cache: FileCache | None = None

    def _ensure_client(self) -> WorkspaceClient:
        """Ensure the WorkspaceClient is initialized.

        Returns:
            The WorkspaceClient instance.
        """
        if self.client is None:
            self.client = WorkspaceClient()
        return self.client

    def _sanitize_path_component(self, value: str) -> str:
        """Sanitize a string for safe use in file paths.

        Prevents path traversal attacks by removing dangerous characters.

        Args:
            value: The string to sanitize.

        Returns:
            A sanitized string safe for use in paths.
        """
        # Remove path traversal sequences
        sanitized = value.replace("..", "").replace("/", "_").replace("\\", "_")
        # Keep only alphanumeric, dots, hyphens, underscores, and @
        sanitized = re.sub(r"[^a-zA-Z0-9._@-]", "_", sanitized)
        # Remove leading/trailing dots and spaces
        sanitized = sanitized.strip(". ")
        # Ensure non-empty
        return sanitized or "unknown"

    def _get_user_name(self) -> str:
        """Get the current user's email/username (sanitized for path safety).

        Returns:
            The sanitized user's email address.
        """
        if self._user_name is None:
            client = self._ensure_client()
            me = client.current_user.me()
            raw_name = me.user_name or "unknown"
            self._user_name = self._sanitize_path_component(raw_name)
        return self._user_name

    def _get_source_path(self) -> Path:
        """Get the source directory path.

        Returns:
            Path to the source directory.
        """
        source = self.config.sync.source
        if source.startswith("./"):
            source = source[2:]
        return Path.cwd() / source

    def _load_gitignore_spec(self, source_path: Path) -> pathspec.PathSpec:
        """Load and cache the combined PathSpec from .gitignore and default patterns.

        This method combines patterns from:
        1. DEFAULT_EXCLUDE_PATTERNS (always applied)
        2. .gitignore file (if present)
        3. User-configured exclude patterns

        Args:
            source_path: The source directory path.

        Returns:
            A PathSpec object for matching files to exclude.
        """
        gitignore_path = source_path / ".gitignore"
        gitignore_mtime = 0.0

        if gitignore_path.exists():
            try:
                gitignore_mtime = gitignore_path.stat().st_mtime
            except OSError:
                pass

        # Return cached spec if .gitignore hasn't changed
        if self._pathspec is not None and gitignore_mtime == self._pathspec_mtime:
            return self._pathspec

        # Combine all patterns
        all_patterns: list[str] = []

        # Add default patterns
        all_patterns.extend(DEFAULT_EXCLUDE_PATTERNS)

        # Add .gitignore patterns if file exists
        if gitignore_path.exists():
            try:
                with open(gitignore_path) as f:
                    for line in f:
                        line = line.strip()
                        # Skip empty lines and comments
                        if line and not line.startswith("#"):
                            all_patterns.append(line)
            except OSError:
                pass  # Ignore read errors

        # Add user-configured patterns
        all_patterns.extend(self.config.sync.exclude)

        # Create and cache the PathSpec
        self._pathspec = pathspec.PathSpec.from_lines("gitwildmatch", all_patterns)
        self._pathspec_mtime = gitignore_mtime

        return self._pathspec

    def _should_exclude(self, path: Path, base_path: Path) -> bool:
        """Check if a path should be excluded from sync.

        Uses gitignore-style pattern matching, similar to Databricks CLI.

        Args:
            path: Path to check.
            base_path: Base directory path.

        Returns:
            True if the path should be excluded.
        """
        spec = self._load_gitignore_spec(base_path)
        rel_path = str(path.relative_to(base_path))

        # For directories, also check with trailing slash (gitignore convention)
        if path.is_dir():
            return spec.match_file(rel_path) or spec.match_file(rel_path + "/")

        return spec.match_file(rel_path)

    def _get_file_cache(self) -> FileCache:
        """Get or create the file cache.

        Returns:
            The FileCache instance.
        """
        if self._file_cache is None:
            self._file_cache = FileCache(self._get_source_path())
        return self._file_cache

    def _get_all_files(self) -> list[Path]:
        """Get all non-excluded files in the source directory.

        Returns:
            List of file paths.
        """
        source_path = self._get_source_path()
        if not source_path.exists():
            return []

        files: list[Path] = []
        for root, dirs, filenames in os.walk(source_path):
            root_path = Path(root)

            # Filter out excluded directories
            dirs[:] = [
                d for d in dirs if not self._should_exclude(root_path / d, source_path)
            ]

            for filename in filenames:
                file_path = root_path / filename
                if not self._should_exclude(file_path, source_path):
                    files.append(file_path)

        return files

    def needs_sync(self) -> bool:
        """Check if files need to be synchronized using hash-based detection.

        Returns:
            True if sync is needed.
        """
        if not self.config.sync.enabled:
            return False

        # Always sync on first run
        if not self._synced:
            return True

        # Check if any files have been modified or deleted using hash comparison
        all_files = self._get_all_files()
        file_cache = self._get_file_cache()

        # Early return: check for deleted files first (cheap operation)
        deleted_files = file_cache.get_deleted_files(all_files)
        if deleted_files:
            return True

        # Early return: stop at first changed file
        return file_cache.has_any_changed(all_files)

    def _validate_sizes(self, files: list[Path]) -> dict[Path, int]:
        """Validate file sizes against configured limits.

        Args:
            files: List of file paths to validate.

        Returns:
            Dict mapping file paths to their sizes (for reuse in other methods).

        Raises:
            FileSizeError: If any file or total size exceeds limits.
        """
        max_file_size = self.config.sync.max_file_size_mb
        max_total_size = self.config.sync.max_size_mb

        total_size = 0
        file_sizes: dict[Path, int] = {}
        for file_path in files:
            try:
                size = file_path.stat().st_size
                file_sizes[file_path] = size
                total_size += size

                # Check individual file size
                if max_file_size is not None:
                    size_mb = size / (1024 * 1024)
                    if size_mb > max_file_size:
                        raise FileSizeError(
                            f"File '{file_path.name}' ({size_mb:.1f}MB) "
                            f"exceeds limit ({max_file_size}MB)"
                        )
            except OSError:
                pass  # Skip files that can't be read

        # Check total size
        if max_total_size is not None:
            total_size_mb = total_size / (1024 * 1024)
            if total_size_mb > max_total_size:
                raise FileSizeError(
                    f"Project size ({total_size_mb:.1f}MB) exceeds limit "
                    f"({max_total_size}MB)\n"
                    "Consider excluding large files in .databricks-kernel.yaml"
                )

        return file_sizes

    def _create_zip(self, files: list[Path] | None = None) -> bytes:
        """Create a zip archive of the source directory.

        Args:
            files: Optional list of file paths to include. If None, uses os.walk
                to discover files (for backward compatibility).

        Returns:
            The zip file contents as bytes.
        """
        source_path = self._get_source_path()
        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            if files is not None:
                # Use pre-computed file list (avoids duplicate os.walk)
                for file_path in files:
                    arcname = file_path.relative_to(source_path)
                    zf.write(file_path, arcname)
            else:
                # Fallback: discover files via os.walk
                for root, dirs, filenames in os.walk(source_path):
                    root_path = Path(root)

                    # Filter out excluded directories
                    dirs[:] = [
                        d
                        for d in dirs
                        if not self._should_exclude(root_path / d, source_path)
                    ]

                    for filename in filenames:
                        file_path = root_path / filename
                        if not self._should_exclude(file_path, source_path):
                            arcname = file_path.relative_to(source_path)
                            zf.write(file_path, arcname)

        return zip_buffer.getvalue()

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """Format file size in human-readable format.

        Args:
            size_bytes: Size in bytes.

        Returns:
            Formatted size string (e.g., "2.5 MB").
        """
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.1f} MB"

    def sync(self) -> SyncStats:
        """Synchronize files to DBFS.

        Returns:
            Sync statistics including changed files, sizes, and duration.

        Raises:
            FileSizeError: If file size limits are exceeded.
        """
        start_time = time.time()

        dbfs_dir = f"/tmp/jupyter_kernel/{self.session_id}"
        dbfs_zip_path = f"{dbfs_dir}/project.zip"

        # Get all files and validate sizes (also returns size info for reuse)
        all_files = self._get_all_files()
        file_sizes = self._validate_sizes(all_files)

        # Get changed files and statistics (reuse size info to avoid duplicate stat())
        file_cache = self._get_file_cache()
        changed_files, stats, computed_hashes = file_cache.get_changed_files(
            all_files, file_sizes
        )

        # Create zip archive (reuse file list to avoid duplicate os.walk)
        zip_data = self._create_zip(all_files)

        # Upload to DBFS using SDK's high-level API
        client = self._ensure_client()
        with client.dbfs.open(dbfs_zip_path, write=True, overwrite=True) as f:
            f.write(zip_data)

        # Remove deleted files from cache
        deleted_files = file_cache.get_deleted_files(all_files)
        for rel_path in deleted_files:
            file_cache.remove(rel_path)

        # Update cache (reuse computed hashes to avoid recomputation)
        file_cache.update(all_files, computed_hashes)
        file_cache.save()
        self._synced = True

        # Calculate duration and set path
        stats.sync_duration = time.time() - start_time
        stats.dbfs_path = dbfs_zip_path

        # Log statistics
        logger.info(
            "Sync complete: %d changed (%s), %d skipped, %.1fs",
            stats.changed_files,
            self._format_size(stats.changed_size),
            stats.skipped_files,
            stats.sync_duration,
        )

        return stats

    def get_setup_code(self, dbfs_path: str) -> str:
        """Generate setup code to run on the remote cluster.

        This code extracts the zip file and adds the directory to sys.path.

        Args:
            dbfs_path: The DBFS path where the zip was uploaded.

        Returns:
            Python code to execute on the remote cluster.
        """
        # Use /Workspace/Users/{email}/ which is allowed on Shared clusters
        user_name = self._get_user_name()
        workspace_extract_dir = (
            f"/Workspace/Users/{user_name}/jupyter_kernel/{self.session_id}"
        )

        return f"""
import sys
import zipfile
import os
import shutil

# Extract to /Workspace/Users/ (allowed on Shared clusters with Unity Catalog)
_extract_dir = "{workspace_extract_dir}"
_dbfs_zip_path = "dbfs:{dbfs_path}"

# Remove old extracted directory if exists
if os.path.exists(_extract_dir):
    shutil.rmtree(_extract_dir)

# Create extract directory
os.makedirs(_extract_dir, exist_ok=True)

# Copy from DBFS to Workspace and extract
_local_zip = _extract_dir + "/project.zip"
dbutils.fs.cp(_dbfs_zip_path, "file:" + _local_zip)

with zipfile.ZipFile(_local_zip, 'r') as zf:
    zf.extractall(_extract_dir)

# Remove local zip file
os.remove(_local_zip)

# Add to sys.path if not already there
if _extract_dir not in sys.path:
    sys.path.insert(0, _extract_dir)

# Clean up variables
del _extract_dir, _dbfs_zip_path, _local_zip
"""

    def cleanup(self) -> None:
        """Clean up DBFS and Workspace files."""
        if not self._synced:
            return

        dbfs_dir = f"/tmp/jupyter_kernel/{self.session_id}"

        try:
            client = self._ensure_client()
            client.dbfs.delete(dbfs_dir, recursive=True)
        except Exception:
            pass  # Ignore cleanup errors

        # Also clean up Workspace directory if user_name is known
        if self._user_name is not None:
            workspace_dir = (
                f"/Workspace/Users/{self._user_name}/jupyter_kernel/{self.session_id}"
            )
            try:
                client = self._ensure_client()
                client.workspace.delete(workspace_dir, recursive=True)
            except Exception:
                pass  # Ignore cleanup errors
