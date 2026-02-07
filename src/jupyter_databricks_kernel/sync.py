"""File synchronization to Databricks cluster.

This module implements file synchronization. It always excludes the .databricks
directory. When use_gitignore is enabled, .gitignore patterns are also applied.
"""

from __future__ import annotations

import functools
import hashlib
import io
import json
import logging
import os
import re
import stat
import tempfile
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pathspec
from databricks.sdk import WorkspaceClient

if TYPE_CHECKING:
    from .config import Config
    from .executor import DatabricksExecutor

logger = logging.getLogger(__name__)

# Sync progress callback type
# Args: message string (e.g., "Collecting files... 10/50")
SyncProgressCallback = Callable[[str], None]

CACHE_FILE_NAME = ".jupyter-databricks-kernel-cache.json"
CACHE_VERSION = 1

# Default patterns that are always excluded, matching Databricks CLI behavior.
# See: https://github.com/databricks/cli/blob/main/libs/git/view.go
DEFAULT_EXCLUDE_PATTERNS = [
    ".databricks",
    ".git",
    ".venv",
    CACHE_FILE_NAME,  # Exclude legacy cache file in project root
]


def get_cache_dir() -> Path:
    """Get XDG-compliant cache directory path.

    Returns the cache directory following XDG Base Directory specification:
    - If $XDG_CACHE_HOME is set: $XDG_CACHE_HOME/jupyter-databricks-kernel
    - Otherwise: ~/.cache/jupyter-databricks-kernel

    Note: The directory is NOT created by this function. It will be created
    by save() when the cache is written.

    Returns:
        Path to the cache directory.
    """
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        base = Path(xdg_cache)
    else:
        base = Path.home() / ".cache"

    return base / "jupyter-databricks-kernel"


def get_project_hash(source_path: Path) -> str:
    """Generate a unique hash for the project based on absolute path.

    Uses SHA-256 hash of the resolved absolute path, truncated to 16 characters.
    This provides sufficient uniqueness while keeping filenames reasonable.

    Args:
        source_path: Path to the project source directory.

    Returns:
        16-character hexadecimal hash string.
    """
    abs_path = str(source_path.resolve())
    return hashlib.sha256(abs_path.encode()).hexdigest()[:16]


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
    cluster_zip_path: str = ""


@dataclass
class FileCache:
    """MD5 hash-based file cache for change detection.

    Design note:
        The changed_files tracking is used for statistics display only.
        This implementation intentionally does NOT use incremental upload,
        because all files are bundled into a single zip archive for atomic
        deployment to DBFS.
    """

    source_path: Path
    _cache: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Load cache from file after initialization."""
        self._load()

    @functools.cached_property
    def cache_path(self) -> Path:
        """Get the cache file path.

        Returns XDG-compliant cache path:
        $XDG_CACHE_HOME/jupyter-databricks-kernel/<project_hash>.json
        or ~/.cache/jupyter-databricks-kernel/<project_hash>.json

        Note: This is a cached_property to avoid recalculating the hash
        on every access. The source_path is immutable after initialization.
        """
        cache_dir = get_cache_dir()
        project_hash = get_project_hash(self.source_path)
        return cache_dir / f"{project_hash}.json"

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
        """Save cache to file atomically.

        Uses a secure temporary file and atomic rename to prevent corruption
        from concurrent access, crashes, or symlink attacks.
        """
        fd = None
        tmp_path = None
        try:
            # Ensure cache directory exists
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)

            # Preserve permissions from existing file if present
            original_mode = None
            if self.cache_path.exists():
                original_mode = self.cache_path.stat().st_mode

            data = {
                "version": CACHE_VERSION,
                "files": self._cache,
            }

            # Create secure temporary file in same directory (for atomic rename)
            # O_EXCL prevents symlink attacks, unique name prevents collisions
            fd, tmp_path_str = tempfile.mkstemp(
                suffix=".tmp",
                prefix=".cache-",
                dir=self.cache_path.parent,
            )
            tmp_path = Path(tmp_path_str)

            with os.fdopen(fd, "w") as f:
                fd = None  # fd is now owned by the file object
                json.dump(data, f, indent=2)
                # Flush and fsync for crash safety
                f.flush()
                os.fsync(f.fileno())

            # Restore original permissions if they existed
            if original_mode is not None:
                os.chmod(tmp_path, stat.S_IMODE(original_mode))

            # Atomic rename (works on both POSIX and Windows)
            os.replace(tmp_path, self.cache_path)
            tmp_path = None  # Rename succeeded, no cleanup needed
        except OSError as e:
            logger.warning("Failed to save cache: %s", e)
        finally:
            # Clean up: close fd if still open, remove temp file if exists
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass

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
        self,
        files: list[Path],
        file_sizes: dict[Path, int] | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> tuple[list[Path], SyncStats, dict[str, str]]:
        """Get list of changed files and sync statistics.

        Args:
            files: List of file paths to check.
            file_sizes: Optional dict of pre-computed file sizes (path -> size).
                If provided, sizes are reused instead of calling stat() again.
            on_progress: Optional callback for progress updates.

        Returns:
            Tuple of (changed files list, sync statistics, computed hashes).
            The computed hashes dict maps relative paths to their MD5 hashes,
            which can be passed to update() to avoid recomputing.
        """
        changed: list[Path] = []
        stats = SyncStats(total_files=len(files))
        computed_hashes: dict[str, str] = {}
        total = len(files)

        for i, file_path in enumerate(files):
            if on_progress:
                on_progress(f"Hashing files... {i + 1}/{total}")

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
    """Synchronizes local files to Databricks cluster.

    The exclusion logic follows this priority:
    1. .databricks directory (always excluded)
    2. .gitignore patterns (only when use_gitignore is True)
    3. User-configured exclude patterns from config file
    """

    def __init__(
        self,
        config: Config,
        session_id: str,
        client: WorkspaceClient | None = None,
    ) -> None:
        """Initialize file sync.

        Args:
            config: Kernel configuration.
            session_id: Session identifier for DBFS paths.
            client: Optional WorkspaceClient instance for dependency injection.
                If not provided, a client will be created lazily when needed.
        """
        self.config = config
        self.client = client
        self.session_id = session_id
        self._synced = False
        self._user_name: str | None = None
        self._pathspec: pathspec.PathSpec | None = None
        self._pathspec_mtime: float = 0.0
        self._file_cache: FileCache | None = None
        self._command_context_id: str | None = None

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

        For service principals, user_name may not exist. Falls back to
        application_id, display_name, or "unknown" in that order.

        Returns:
            The sanitized user's email address or identifier.
        """
        if self._user_name is None:
            client = self._ensure_client()
            me = client.current_user.me()
            # NOTE: Service principals may not have user_name attribute
            raw_name = (
                getattr(me, "user_name", None)
                or getattr(me, "application_id", None)
                or getattr(me, "display_name", None)
                or "unknown"
            )
            self._user_name = self._sanitize_path_component(raw_name)
        return self._user_name

    def _get_source_path(self) -> Path:
        """Get the source directory path.

        If pyproject.toml was found, resolves source relative to its location.
        Otherwise, falls back to cwd for backward compatibility.

        Returns:
            Path to the source directory.
        """
        source = self.config.sync.source
        if source.startswith("./"):
            source = source[2:]

        # Use base_path (pyproject.toml location) if available, otherwise cwd
        base = self.config.base_path if self.config.base_path else Path.cwd()
        return base / source

    def _load_gitignore_spec(self, source_path: Path) -> pathspec.PathSpec:
        """Load and cache the combined PathSpec from default and configured patterns.

        This method combines patterns from:
        1. DEFAULT_EXCLUDE_PATTERNS (always applied)
        2. .gitignore file (only when use_gitignore is True)
        3. User-configured exclude patterns

        Args:
            source_path: The source directory path.

        Returns:
            A PathSpec object for matching files to exclude.
        """
        gitignore_path = source_path / ".gitignore"
        gitignore_mtime = 0.0

        # Only check .gitignore mtime if use_gitignore is enabled
        if self.config.sync.use_gitignore and gitignore_path.exists():
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

        # Add .gitignore patterns only when use_gitignore is True
        if self.config.sync.use_gitignore and gitignore_path.exists():
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

    def _get_all_files(
        self,
        on_progress: SyncProgressCallback | None = None,
    ) -> list[Path]:
        """Get all non-excluded files in the source directory.

        Args:
            on_progress: Optional callback for progress updates.

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
                if file_path.is_file() and not self._should_exclude(
                    file_path, source_path
                ):
                    files.append(file_path)
                    if on_progress:
                        on_progress(f"Collecting files... {len(files)}")

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

    def _validate_sizes(self, files: list[Path], source_path: Path) -> dict[Path, int]:
        """Validate file sizes against configured limits.

        Args:
            files: List of file paths to validate.
            source_path: Base path for relative path display in error messages.

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
                        # Use os.path.relpath for safer relative path computation
                        # (doesn't raise ValueError if paths are on different drives)
                        rel_path = os.path.relpath(file_path, source_path)
                        raise FileSizeError(
                            f"File '{rel_path}' ({size_mb:.1f}MB) "
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
                    "Consider adding exclude patterns in pyproject.toml "
                    "[tool.jupyter-databricks-kernel.sync]"
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
                    if file_path.is_file():
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
                        if file_path.is_file() and not self._should_exclude(
                            file_path, source_path
                        ):
                            arcname = file_path.relative_to(source_path)
                            zf.write(file_path, arcname)

        return zip_buffer.getvalue()

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """Format file size in human-readable format.

        Args:
            size_bytes: Size in bytes.

        Returns:
            Formatted size string (e.g., "1 KB", "2.5 MB").
        """
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            kb = size_bytes / 1024
            return f"{kb:.0f} KB" if kb.is_integer() else f"{kb:.1f} KB"
        else:
            mb = size_bytes / (1024 * 1024)
            return f"{mb:.0f} MB" if mb.is_integer() else f"{mb:.1f} MB"

    def sync(
        self,
        on_progress: SyncProgressCallback | None = None,
        executor: DatabricksExecutor | None = None,
    ) -> SyncStats:
        """Synchronize files to Databricks cluster.

        Args:
            on_progress: Optional callback for progress updates.
            executor: Optional DatabricksExecutor for sharing execution context.

        Returns:
            Sync statistics including changed files, sizes, and duration.

        Raises:
            FileSizeError: If file size limits are exceeded.
        """
        from datetime import timedelta

        from databricks.sdk.service import compute

        start_time = time.time()

        # Get all files and validate sizes (also returns size info for reuse)
        source_path = self._get_source_path()

        all_files = self._get_all_files(on_progress=on_progress)
        file_sizes = self._validate_sizes(all_files, source_path)
        total_files = len(all_files)

        # Get changed files and statistics (reuse size info to avoid duplicate stat())
        file_cache = self._get_file_cache()
        changed_files, stats, computed_hashes = file_cache.get_changed_files(
            all_files, file_sizes, on_progress=on_progress
        )

        if on_progress:
            on_progress(f"Creating archive ({total_files} files)...")

        # Create zip archive (reuse file list to avoid duplicate os.walk)
        zip_data = self._create_zip(all_files)

        if on_progress:
            on_progress(f"Uploading ({self._format_size(len(zip_data))})...")

        # Upload via Command API (chunked Base64 transfer)
        client = self._ensure_client()
        import base64

        # Encode to Base64
        zip_b64 = base64.b64encode(zip_data).decode("utf-8")

        # Split into 1MB chunks
        chunk_size = 1024 * 1024
        chunks = [
            zip_b64[i : i + chunk_size] for i in range(0, len(zip_b64), chunk_size)
        ]

        # Use executor's context if provided, otherwise create minimal execution context
        context_id: str | None
        if executor and executor.context_id:
            context_id = executor.context_id
        elif self._command_context_id is None:
            response = client.command_execution.create(
                cluster_id=self.config.cluster_id,
                language=compute.Language.PYTHON,
            ).result()
            self._command_context_id = response.id if response else None
            context_id = self._command_context_id
        else:
            context_id = self._command_context_id

        if context_id is None:
            raise RuntimeError("Failed to create or retrieve execution context")

        # Create target directory on cluster with UID fallback
        target_dir = f"/tmp/jupyter_databricks_kernel_{self.session_id}"
        mkdir_code = f"""
import os
target_dir = "{target_dir}"
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
        result = client.command_execution.execute(
            cluster_id=self.config.cluster_id,
            context_id=context_id,
            language=compute.Language.PYTHON,
            command=mkdir_code,
        ).result(timeout=timedelta(minutes=5))

        if result and result.results and result.results.cause:
            raise RuntimeError(f"Failed to create directory: {result.results.cause}")
        if result and result.status != compute.CommandStatus.FINISHED:
            raise RuntimeError(f"Failed to create directory: status={result.status}")

        # Get actual directory path from result
        # (may have UID suffix if permission error occurred)
        actual_dir = (
            result.results.data.strip()
            if result and result.results and result.results.data
            else target_dir
        )
        cluster_zip_path = f"{actual_dir}/project.zip"
        tmp_b64_path = f"{actual_dir}/project.zip.b64"

        # Send chunks via Command API
        for i, chunk in enumerate(chunks):
            mode = "w" if i == 0 else "a"
            # Escape quotes in chunk for Python string
            chunk_escaped = chunk.replace("\\", "\\\\").replace('"', '\\"')
            code = f'''
with open("{tmp_b64_path}", "{mode}") as f:
    f.write("{chunk_escaped}")
'''
            # Execute chunk write
            result = client.command_execution.execute(
                cluster_id=self.config.cluster_id,
                context_id=context_id,
                language=compute.Language.PYTHON,
                command=code,
            ).result(timeout=timedelta(minutes=5))

            if result and result.results and result.results.cause:
                raise RuntimeError(
                    f"Chunk {i + 1}/{len(chunks)} failed: {result.results.cause}"
                )
            if result and result.status != compute.CommandStatus.FINISHED:
                raise RuntimeError(
                    f"Chunk {i + 1}/{len(chunks)} transfer failed: "
                    f"status={result.status}"
                )

            if on_progress:
                on_progress(f"Transferred chunk {i + 1}/{len(chunks)}...")

        # Decode Base64 on cluster
        decode_code = f'''
import base64
import os
with open("{tmp_b64_path}", "r") as f:
    b64_data = f.read()
decoded = base64.b64decode(b64_data)
with open("{cluster_zip_path}", "wb") as f:
    f.write(decoded)
os.remove("{tmp_b64_path}")
'''

        result = client.command_execution.execute(
            cluster_id=self.config.cluster_id,
            context_id=context_id,
            language=compute.Language.PYTHON,
            command=decode_code,
        ).result(timeout=timedelta(minutes=5))

        # Check for errors in result.results.cause (Python exceptions)
        if result and result.results and result.results.cause:
            raise RuntimeError(f"Base64 decode failed: {result.results.cause}")
        if result and result.status != compute.CommandStatus.FINISHED:
            raise RuntimeError(
                f"Base64 decode failed on cluster: status={result.status}"
            )

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
        stats.cluster_zip_path = cluster_zip_path

        # Log statistics
        logger.info(
            "Sync complete: %d changed (%s), %d skipped, %.1fs",
            stats.changed_files,
            self._format_size(stats.changed_size),
            stats.skipped_files,
            stats.sync_duration,
        )

        return stats

    def get_setup_code(self, cluster_zip_path: str) -> str:
        """Generate setup code to run on the remote cluster.

        This code extracts the zip file and adds the directory to sys.path.

        Args:
            cluster_zip_path: The cluster path where the zip was uploaded.

        Returns:
            Python code to execute on the remote cluster.
        """
        steps = self.get_setup_steps(cluster_zip_path)
        return "\n".join(code for _, code in steps)

    def get_setup_steps(self, cluster_zip_path: str) -> list[tuple[str, str]]:
        """Generate setup steps to run on the remote cluster.

        Each step is a tuple of (description, code) that can be executed
        individually for progress tracking.

        Args:
            cluster_zip_path: The cluster path where the zip was uploaded.

        Returns:
            List of (description, code) tuples.
        """
        # TODO: Unify custom path branch to use Command API method instead of DBFS
        # Currently this branch still uses dbutils.fs.cp which requires DBFS permissions
        # See #162 for related scalability improvements
        # Check if custom workspace_extract_dir is configured
        if self.config.sync.workspace_extract_dir:
            workspace_extract_dir = self.config.sync.workspace_extract_dir
            # Use custom path directly without fallback
            return [
                (
                    "Preparing directory",
                    f'''
import sys
import zipfile
import os
import shutil

_extract_dir = "{workspace_extract_dir}"
_dbfs_zip_path = "dbfs:{cluster_zip_path}"

if os.path.exists(_extract_dir):
    shutil.rmtree(_extract_dir)
os.makedirs(_extract_dir, exist_ok=True)
''',
                ),
                (
                    "Copying from DBFS",
                    f'''
_extract_dir = "{workspace_extract_dir}"
_dbfs_zip_path = "dbfs:{cluster_zip_path}"
_local_zip = _extract_dir + "/project.zip"
dbutils.fs.cp(_dbfs_zip_path, "file:" + _local_zip)
''',
                ),
                (
                    "Extracting files",
                    f'''
_extract_dir = "{workspace_extract_dir}"
_local_zip = _extract_dir + "/project.zip"
with zipfile.ZipFile(_local_zip, 'r') as zf:
    zf.extractall(_extract_dir)
os.remove(_local_zip)
''',
                ),
                (
                    "Configuring paths",
                    f'''
_extract_dir = "{workspace_extract_dir}"
if _extract_dir not in sys.path:
    sys.path.insert(0, _extract_dir)
os.chdir(_extract_dir)
del _extract_dir, _dbfs_zip_path, _local_zip
''',
                ),
            ]

        # Use intelligent fallback: try /Workspace/Users/ first,
        # fallback to /tmp/workspace
        user_name = self._get_user_name()
        workspace_extract_dir = (
            f"/Workspace/Users/{user_name}/jupyter_databricks_kernel/{self.session_id}"
        )
        # NOTE: Use /workspace suffix to avoid confusion with zip path
        fallback_extract_dir = (
            f"/tmp/jupyter_databricks_kernel_{self.session_id}/workspace"
        )

        return [
            (
                "Preparing directory",
                f'''
import sys
import zipfile
import os
import shutil
import logging

_logger = logging.getLogger("jupyter_databricks_kernel")

# Try /Workspace/Users/ first, fallback to /tmp/workspace if it fails
_primary_dir = "{workspace_extract_dir}"
_fallback_dir = "{fallback_extract_dir}"

try:
    if os.path.exists(_primary_dir):
        shutil.rmtree(_primary_dir)
    os.makedirs(_primary_dir, exist_ok=True)
    _extract_dir = _primary_dir
except (OSError, PermissionError, FileNotFoundError) as e:
    # Fallback to /tmp/workspace for service principals or permission issues
    _logger.info(
        f"Failed to create {{_primary_dir}}: {{e.__class__.__name__}}: {{e}}. "
        f"Falling back to {{_fallback_dir}}"
    )
    if os.path.exists(_fallback_dir):
        shutil.rmtree(_fallback_dir)
    os.makedirs(_fallback_dir, exist_ok=True)
    _extract_dir = _fallback_dir
''',
            ),
            (
                "Extracting files",
                f"""
# Zip is already on cluster at {cluster_zip_path}
_cluster_zip = "{cluster_zip_path}"
with zipfile.ZipFile(_cluster_zip, 'r') as zf:
    zf.extractall(_extract_dir)
os.remove(_cluster_zip)
""",
            ),
            (
                "Configuring paths",
                """
if _extract_dir not in sys.path:
    sys.path.insert(0, _extract_dir)
os.chdir(_extract_dir)
del _extract_dir, _primary_dir, _fallback_dir, _logger
""",
            ),
        ]

    def cleanup(self) -> None:
        """Clean up DBFS and Workspace files.

        Note: This method cleans up DBFS and Workspace paths. Local filesystem
        paths (like /tmp/ on the cluster) are not cleaned up as they are
        inaccessible from the kernel side and typically get cleaned up
        automatically or overwritten in subsequent sessions.
        """
        if not self._synced:
            return

        dbfs_dir = f"/tmp/jupyter_databricks_kernel/{self.session_id}"

        try:
            client = self._ensure_client()
            client.dbfs.delete(dbfs_dir, recursive=True)
        except Exception as e:
            logger.debug("DBFS cleanup error (ignored): %s", e)

        # Clean up Workspace directory if user_name is known
        # This handles the primary path for regular users
        if self._user_name is not None:
            workspace_dir = (
                f"/Workspace/Users/{self._user_name}"
                f"/jupyter_databricks_kernel/{self.session_id}"
            )
            try:
                client = self._ensure_client()
                client.workspace.delete(workspace_dir, recursive=True)
            except Exception as e:
                logger.debug("Workspace cleanup error (ignored): %s", e)

        # NOTE: Local filesystem paths used by Command API transfer
        # (e.g., /tmp/jupyter_databricks_kernel_{session_id}/)
        # are not cleaned up here as they require an active
        # execution context. These should be cleaned up via Command API execution
        # when the executor context is available. Files in /tmp/ are typically
        # cleaned up automatically by the cluster or overwritten in subsequent sessions.
