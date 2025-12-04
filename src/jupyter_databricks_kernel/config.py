"""Configuration management for Databricks kernel."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class SyncConfig:
    """Configuration for file synchronization."""

    enabled: bool = True
    source: str = "."
    exclude: list[str] = field(
        default_factory=lambda: [
            ".git",
            "__pycache__",
            ".venv",
            "*.pyc",
            ".pytest_cache",
        ]
    )
    max_size_mb: float | None = None
    max_file_size_mb: float | None = None


@dataclass
class Config:
    """Main configuration for the Databricks kernel."""

    cluster_id: str | None = None
    sync: SyncConfig = field(default_factory=SyncConfig)

    @classmethod
    def load(cls, config_path: Path | None = None) -> Config:
        """Load configuration from environment variables and config file.

        Args:
            config_path: Optional path to the config file.
                         Defaults to .databricks-kernel.yaml in current directory.

        Returns:
            Loaded configuration.
        """
        config = cls()

        # Load from environment variables
        config.cluster_id = os.environ.get("DATABRICKS_CLUSTER_ID")

        # Determine config file path
        if config_path is None:
            config_path = Path.cwd() / ".databricks-kernel.yaml"

        # Load from config file if it exists
        if config_path.exists():
            config._load_from_file(config_path)

        return config

    def _load_from_file(self, config_path: Path) -> None:
        """Load configuration from a YAML file.

        Args:
            config_path: Path to the config file.
        """
        with open(config_path) as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}

        # Override cluster_id if specified in file
        if "cluster_id" in data:
            self.cluster_id = data["cluster_id"]

        # Load sync configuration
        if "sync" in data:
            sync_data = data["sync"]
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

    def validate(self) -> list[str]:
        """Validate the configuration.

        Returns:
            List of validation error messages. Empty if valid.
        """
        errors: list[str] = []

        if not self.cluster_id:
            errors.append(
                "DATABRICKS_CLUSTER_ID environment variable is not set. "
                "Please set it to your Databricks cluster ID."
            )

        # Check for DATABRICKS_HOST and DATABRICKS_TOKEN
        if not os.environ.get("DATABRICKS_HOST"):
            errors.append(
                "DATABRICKS_HOST environment variable is not set. "
                "Please set it to your Databricks workspace URL."
            )

        if not os.environ.get("DATABRICKS_TOKEN"):
            errors.append(
                "DATABRICKS_TOKEN environment variable is not set. "
                "Please set it to your Databricks personal access token."
            )

        return errors
