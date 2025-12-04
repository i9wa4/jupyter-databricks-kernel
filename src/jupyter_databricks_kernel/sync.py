"""File synchronization to Databricks DBFS."""

from __future__ import annotations

import fnmatch
import io
import os
import re
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

from databricks.sdk import WorkspaceClient

if TYPE_CHECKING:
    from .config import Config


class FileSync:
    """Synchronizes local files to Databricks DBFS."""

    def __init__(self, config: Config, session_id: str) -> None:
        """Initialize file sync.

        Args:
            config: Kernel configuration.
            session_id: Session identifier for DBFS paths.
        """
        self.config = config
        self.client: WorkspaceClient | None = None
        self.session_id = session_id
        self.last_sync_mtime: float = 0.0
        self._synced = False
        self._user_name: str | None = None

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

    def _should_exclude(self, path: Path, base_path: Path) -> bool:
        """Check if a path should be excluded from sync.

        Args:
            path: Path to check.
            base_path: Base directory path.

        Returns:
            True if the path should be excluded.
        """
        rel_path = str(path.relative_to(base_path))

        for pattern in self.config.sync.exclude:
            # Check if any part of the path matches the pattern
            if fnmatch.fnmatch(path.name, pattern):
                return True
            if fnmatch.fnmatch(rel_path, pattern):
                return True
            # Check for directory patterns
            for part in path.parts:
                if fnmatch.fnmatch(part, pattern):
                    return True

        return False

    def _get_latest_mtime(self) -> float:
        """Get the latest modification time of files in source directory.

        Returns:
            The latest mtime as a float.
        """
        source_path = self._get_source_path()
        if not source_path.exists():
            return 0.0

        latest_mtime = 0.0
        for root, dirs, files in os.walk(source_path):
            root_path = Path(root)

            # Filter out excluded directories
            dirs[:] = [
                d for d in dirs if not self._should_exclude(root_path / d, source_path)
            ]

            for file in files:
                file_path = root_path / file
                if not self._should_exclude(file_path, source_path):
                    try:
                        mtime = file_path.stat().st_mtime
                        if mtime > latest_mtime:
                            latest_mtime = mtime
                    except OSError:
                        pass

        return latest_mtime

    def needs_sync(self) -> bool:
        """Check if files need to be synchronized.

        Returns:
            True if sync is needed.
        """
        if not self.config.sync.enabled:
            return False

        # Always sync on first run
        if not self._synced:
            return True

        # Check if any files have been modified
        current_mtime = self._get_latest_mtime()
        return current_mtime > self.last_sync_mtime

    def _create_zip(self) -> bytes:
        """Create a zip archive of the source directory.

        Returns:
            The zip file contents as bytes.
        """
        source_path = self._get_source_path()
        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(source_path):
                root_path = Path(root)

                # Filter out excluded directories
                dirs[:] = [
                    d
                    for d in dirs
                    if not self._should_exclude(root_path / d, source_path)
                ]

                for file in files:
                    file_path = root_path / file
                    if not self._should_exclude(file_path, source_path):
                        arcname = file_path.relative_to(source_path)
                        zf.write(file_path, arcname)

        return zip_buffer.getvalue()

    def sync(self) -> str:
        """Synchronize files to DBFS.

        Returns:
            The DBFS path where files were uploaded.
        """
        dbfs_dir = f"/tmp/jupyter_kernel/{self.session_id}"
        dbfs_zip_path = f"{dbfs_dir}/project.zip"

        # Create zip archive
        zip_data = self._create_zip()

        # Upload to DBFS using SDK's high-level API
        client = self._ensure_client()
        with client.dbfs.open(dbfs_zip_path, write=True, overwrite=True) as f:
            f.write(zip_data)

        # Update sync state
        self.last_sync_mtime = self._get_latest_mtime()
        self._synced = True

        return dbfs_zip_path

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
