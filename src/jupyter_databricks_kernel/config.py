"""Configuration management for Databricks kernel."""

from __future__ import annotations

import configparser
import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


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

    @classmethod
    def load(cls, config_path: Path | None = None) -> Config:
        """Load configuration from environment variables and config files.

        Priority order for cluster_id:
        1. DATABRICKS_CLUSTER_ID environment variable (highest priority)
        2. ~/.databrickscfg cluster_id (from active profile)

        Sync settings are loaded from pyproject.toml.

        Args:
            config_path: Optional path to the pyproject.toml file for sync settings.
                         Defaults to pyproject.toml in current directory.

        Returns:
            Loaded configuration.
        """
        config = cls()

        # Load cluster_id from environment variable (highest priority)
        config.cluster_id = os.environ.get("DATABRICKS_CLUSTER_ID")

        # Load cluster_id from databrickscfg if not set by env var
        if config.cluster_id is None:
            config._load_cluster_id_from_databrickscfg()

        # Determine config file path for sync settings
        if config_path is None:
            config_path = Path.cwd() / "pyproject.toml"

        # Load sync settings from config file if it exists
        if config_path.exists():
            config._load_from_pyproject(config_path)

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
            print(
                f"Warning: Failed to parse {databrickscfg_path}: {e}. "
                "Skipping databrickscfg configuration.",
                file=sys.stderr,
            )
            return

        if profile not in parser:
            return

        if "cluster_id" in parser[profile]:
            self.cluster_id = parser[profile]["cluster_id"]

    def _load_from_pyproject(self, config_path: Path) -> None:
        """Load sync configuration from pyproject.toml.

        Note: cluster_id is no longer read from pyproject.toml.
        Use DATABRICKS_CLUSTER_ID environment variable or ~/.databrickscfg.

        Args:
            config_path: Path to pyproject.toml.
        """
        try:
            with open(config_path, "rb") as f:
                data = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            print(
                f"Warning: Failed to parse {config_path}: {e}. "
                "Using default configuration.",
                file=sys.stderr,
            )
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
