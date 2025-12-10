"""Configuration management for Databricks kernel."""

from __future__ import annotations

import configparser
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


@dataclass
class Config:
    """Main configuration for the Databricks kernel."""

    cluster_id: str | None = None
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

    @classmethod
    def load(cls, config_path: Path | None = None) -> Config:
        """Load configuration from environment variables and config files.

        Priority order for cluster_id:
        1. DATABRICKS_CLUSTER_ID environment variable (highest priority)
        2. ~/.databrickscfg cluster_id (from active profile)

        Sync settings are loaded from pyproject.toml.

        Args:
            config_path: Optional path to the pyproject.toml file for sync settings.
                         If not provided, searches current and parent directories.

        Returns:
            Loaded configuration.
        """
        logger.debug("Loading configuration")
        config = cls()

        # Load cluster_id from environment variable (highest priority)
        config.cluster_id = os.environ.get("DATABRICKS_CLUSTER_ID")
        if config.cluster_id:
            logger.debug("Cluster ID from environment: %s", config.cluster_id)

        # Load cluster_id from databrickscfg if not set by env var
        if config.cluster_id is None:
            config._load_cluster_id_from_databrickscfg()

        # Search for pyproject.toml if not explicitly provided
        if config_path is None:
            config_path = cls._find_pyproject_toml()

        # Load sync settings and set base_path if config file exists
        if config_path is not None and config_path.exists():
            config.base_path = config_path.parent
            config._load_from_pyproject(config_path)

        logger.debug(
            "Configuration loaded: cluster_id=%s, sync_enabled=%s, base_path=%s",
            config.cluster_id,
            config.sync.enabled,
            config.base_path,
        )
        return config

    def _load_cluster_id_from_databrickscfg(self) -> None:
        """Load cluster_id from ~/.databrickscfg.

        Reads cluster_id from the active profile in ~/.databrickscfg.
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

        if "cluster_id" in parser[profile]:
            self.cluster_id = parser[profile]["cluster_id"]
            logger.debug(
                "Cluster ID from databrickscfg [%s]: %s", profile, self.cluster_id
            )

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
