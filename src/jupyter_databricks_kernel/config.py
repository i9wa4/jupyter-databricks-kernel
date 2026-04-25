"""Configuration management for Databricks kernel."""

from __future__ import annotations

import configparser
import json
import logging
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SyncConfig:
    """Configuration for file synchronization.

    The sync module applies default exclusion patterns automatically.
    When use_gitignore is True, .gitignore rules are also applied.
    User-specified exclude patterns are applied in addition to those defaults.
    """

    enabled: bool = True
    source: str = "."
    exclude: list[str] = field(default_factory=list)
    max_size_mb: float | None = None
    max_file_size_mb: float | None = None
    use_gitignore: bool = True
    workspace_extract_dir: str | None = None


@dataclass
class Config:
    """Main configuration for the Databricks kernel."""

    cluster_id: str | None = None
    mcp_profile: str | None = None
    sync: SyncConfig = field(default_factory=SyncConfig)
    base_path: Path | None = None

    @staticmethod
    def _find_pyproject_toml() -> Path | None:
        """Find pyproject.toml in current or parent directories.

        Searches from cwd upward, similar to how ruff, pytest, and git
        find their config files.

        Returns:
            Path to pyproject.toml if found, None otherwise.
        """
        current = Path.cwd()
        for directory in [current] + list(current.parents):
            candidate = directory / "pyproject.toml"
            if candidate.exists():
                logger.debug("Found pyproject.toml at %s", candidate)
                return candidate
        logger.debug("No pyproject.toml found in %s or parent directories", current)
        return None

    @staticmethod
    def _find_databricks_config_json() -> Path | None:
        """Find .databricks/config.json in current or parent directories.

        Returns:
            Path to .databricks/config.json if found, None otherwise.
        """
        current = Path.cwd()
        for directory in [current] + list(current.parents):
            candidate = directory / ".databricks" / "config.json"
            if candidate.exists():
                logger.debug("Found .databricks/config.json at %s", candidate)
                return candidate
        return None

    @classmethod
    def load(cls, config_path: Path | None = None) -> Config:
        """Load configuration from environment variables and config files.

        Priority order for cluster_id and mcp_profile:
        1. Environment variables (highest priority)
        2. ~/.databrickscfg (from active profile)
        3. .databricks/config.json (project-local, lowest priority)

        Sync settings are loaded from pyproject.toml.

        Args:
            config_path: Optional path to the pyproject.toml file for sync settings.
                         If not provided, searches current and parent directories.

        Returns:
            Loaded configuration.
        """
        logger.debug("Loading configuration")
        config = cls()

        # Load from environment variables (highest priority)
        config.cluster_id = os.environ.get("DATABRICKS_CLUSTER_ID")
        if config.cluster_id:
            logger.debug("Cluster ID from environment: %s", config.cluster_id)

        config.mcp_profile = os.environ.get("DATABRICKS_MCP_PROFILE")
        if config.mcp_profile:
            logger.debug("MCP profile from environment: %s", config.mcp_profile)

        # Load from databrickscfg if fields not set by env var
        if config.cluster_id is None or config.mcp_profile is None:
            config._load_from_databrickscfg()

        # Load from .databricks/config.json if fields still not set
        if config.cluster_id is None or config.mcp_profile is None:
            databricks_config = cls._find_databricks_config_json()
            if databricks_config is not None:
                config._load_from_databricks_config_json(databricks_config)

        # Search for pyproject.toml if not explicitly provided
        if config_path is None:
            config_path = cls._find_pyproject_toml()

        # Load sync settings and set base_path if config file exists
        if config_path is not None and config_path.exists():
            config.base_path = config_path.parent
            config._load_from_pyproject(config_path)

        # Load workspace_extract_dir from environment variable (highest priority)
        workspace_extract_dir = os.environ.get("JUPYTER_DATABRICKS_KERNEL_EXTRACT_DIR")
        if workspace_extract_dir:
            config.sync.workspace_extract_dir = workspace_extract_dir
            logger.debug(
                "Workspace extract dir from environment: %s", workspace_extract_dir
            )

        logger.debug(
            "Configuration loaded: cluster_id=%s, mcp_profile=%s, sync_enabled=%s, base_path=%s",
            config.cluster_id,
            config.mcp_profile,
            config.sync.enabled,
            config.base_path,
        )
        return config

    def _load_from_databrickscfg(self) -> None:
        """Load cluster_id and mcp_profile from ~/.databrickscfg.

        Reads values from the active profile in ~/.databrickscfg.
        Active profile is determined by DATABRICKS_CONFIG_PROFILE
        environment variable, or 'DEFAULT' if not set.
        """
        databrickscfg_path = Path.home() / ".databrickscfg"
        if not databrickscfg_path.exists():
            return

        profile = os.environ.get("DATABRICKS_CONFIG_PROFILE", "DEFAULT")

        parser = configparser.ConfigParser()
        try:
            parser.read(databrickscfg_path)
        except configparser.Error as e:
            logger.warning("Failed to parse %s: %s", databrickscfg_path, e)
            return

        if profile not in parser:
            return

        if self.cluster_id is None and "cluster_id" in parser[profile]:
            self.cluster_id = parser[profile]["cluster_id"]
            logger.debug(
                "Cluster ID from databrickscfg [%s]: %s", profile, self.cluster_id
            )

        if self.mcp_profile is None and "mcp_profile" in parser[profile]:
            self.mcp_profile = parser[profile]["mcp_profile"]
            logger.debug(
                "MCP profile from databrickscfg [%s]: %s", profile, self.mcp_profile
            )

    def _load_from_databricks_config_json(self, path: Path) -> None:
        """Load cluster_id and mcp_profile from .databricks/config.json.

        Args:
            path: Path to .databricks/config.json.

        Raises:
            ValueError: If config contains workspace_url (intentionally absent
                from schema; workspace identity must come from mcp_profile).
        """
        logger.debug("Loading from %s", path)
        try:
            with open(path) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Failed to parse %s: %s", path, e)
            return

        if "workspace_url" in data:
            raise ValueError(
                f"{path} must not contain 'workspace_url'. "
                "Workspace identity must come from mcp_profile in ~/.databrickscfg."
            )

        if self.cluster_id is None and "cluster_id" in data:
            self.cluster_id = data["cluster_id"]
            logger.debug("Cluster ID from %s: %s", path, self.cluster_id)

        if self.mcp_profile is None and "mcp_profile" in data:
            self.mcp_profile = data["mcp_profile"]
            logger.debug("MCP profile from %s: %s", path, self.mcp_profile)

    def _load_from_pyproject(self, config_path: Path) -> None:
        """Load sync configuration from pyproject.toml.

        Note: cluster_id is no longer read from pyproject.toml.
        Use DATABRICKS_CLUSTER_ID environment variable or ~/.databrickscfg.

        Args:
            config_path: Path to pyproject.toml.
        """
        logger.debug("Loading sync config from %s", config_path)
        try:
            with open(config_path, "rb") as f:
                data = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            logger.warning("Failed to parse %s: %s", config_path, e)
            return

        # Get [tool.jupyter-databricks-kernel] section
        tool_config = data.get("tool", {}).get("jupyter-databricks-kernel", {})
        if not tool_config:
            return

        # Load sync configuration
        if "sync" in tool_config:
            sync_data = tool_config["sync"]
            if "enabled" in sync_data:
                self.sync.enabled = sync_data["enabled"]
            if "source" in sync_data:
                self.sync.source = sync_data["source"]
            if "exclude" in sync_data:
                self.sync.exclude = sync_data["exclude"]
            if "max_size_mb" in sync_data:
                self.sync.max_size_mb = sync_data["max_size_mb"]
            if "max_file_size_mb" in sync_data:
                self.sync.max_file_size_mb = sync_data["max_file_size_mb"]
            if "use_gitignore" in sync_data:
                self.sync.use_gitignore = sync_data["use_gitignore"]
            if "workspace_extract_dir" in sync_data:
                self.sync.workspace_extract_dir = sync_data["workspace_extract_dir"]

    def validate(self) -> list[str]:
        """Validate the configuration.

        Note: Authentication is handled by the Databricks SDK, which
        automatically resolves credentials from environment variables,
        CLI config, or cloud provider authentication.

        Returns:
            List of validation error messages. Empty if valid.
        """
        errors: list[str] = []

        if not self.cluster_id:
            errors.append(
                "Cluster ID is not configured. "
                "Please set DATABRICKS_CLUSTER_ID environment variable or "
                "run 'databricks auth login --configure-cluster'."
            )

        # Validate sync size limits
        if self.sync.max_size_mb is not None and self.sync.max_size_mb <= 0:
            errors.append("max_size_mb must be a positive number.")

        if self.sync.max_file_size_mb is not None and self.sync.max_file_size_mb <= 0:
            errors.append("max_file_size_mb must be a positive number.")

        return errors
