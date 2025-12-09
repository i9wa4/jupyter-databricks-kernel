"""Tests for Config."""

from __future__ import annotations

from pathlib import Path

import pytest

from jupyter_databricks_kernel.config import Config, SyncConfig


class TestSyncConfigDefaults:
    """Tests for SyncConfig default values."""

    def test_default_values(self) -> None:
        """Test that SyncConfig has correct default values."""
        config = SyncConfig()
        assert config.enabled is True
        assert config.source == "."
        assert config.exclude == []
        assert config.max_size_mb is None
        assert config.max_file_size_mb is None
        assert config.use_gitignore is True


class TestConfigDefaults:
    """Tests for Config default values."""

    def test_default_values(self) -> None:
        """Test that Config has correct default values."""
        config = Config()
        assert config.cluster_id is None
        assert config.sync.enabled is True


class TestConfigLoad:
    """Tests for Config.load() method."""

    def test_load_from_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test loading cluster_id from environment variable."""
        monkeypatch.setenv("DATABRICKS_CLUSTER_ID", "env-cluster-123")
        monkeypatch.chdir(tmp_path)

        config = Config.load()
        assert config.cluster_id == "env-cluster-123"

    def test_load_sync_from_pyproject(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test loading sync configuration from pyproject.toml."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""
[tool.jupyter-databricks-kernel.sync]
enabled = false
source = "./src"
exclude = ["*.log", "data/"]
max_size_mb = 100.0
max_file_size_mb = 10.0
use_gitignore = true
""")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DATABRICKS_CLUSTER_ID", raising=False)

        config = Config.load()
        # cluster_id is not loaded from pyproject.toml
        assert config.cluster_id is None
        # sync settings are loaded
        assert config.sync.enabled is False
        assert config.sync.source == "./src"
        assert config.sync.exclude == ["*.log", "data/"]
        assert config.sync.max_size_mb == 100.0
        assert config.sync.max_file_size_mb == 10.0
        assert config.sync.use_gitignore is True

    def test_load_missing_pyproject(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test loading when pyproject.toml doesn't exist."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DATABRICKS_CLUSTER_ID", raising=False)

        config = Config.load()
        assert config.cluster_id is None
        assert config.sync.enabled is True  # Default value

    def test_load_empty_tool_section(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test loading when [tool.jupyter-databricks-kernel] section doesn't exist."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""
[project]
name = "my-project"
""")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DATABRICKS_CLUSTER_ID", raising=False)

        config = Config.load()
        assert config.cluster_id is None
        assert config.sync.enabled is True  # Default value

    def test_load_sync_with_custom_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test loading sync settings from a custom config path."""
        custom_config = tmp_path / "custom" / "config.toml"
        custom_config.parent.mkdir(parents=True)
        custom_config.write_text("""
[tool.jupyter-databricks-kernel.sync]
enabled = false
source = "./custom"
""")
        monkeypatch.delenv("DATABRICKS_CLUSTER_ID", raising=False)

        config = Config.load(config_path=custom_config)
        # cluster_id is not loaded from pyproject.toml
        assert config.cluster_id is None
        # sync settings are loaded from custom path
        assert config.sync.enabled is False
        assert config.sync.source == "./custom"

    def test_load_invalid_toml(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test loading when pyproject.toml has invalid TOML syntax."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("invalid toml [ syntax")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DATABRICKS_CLUSTER_ID", raising=False)

        config = Config.load()
        # Should use default values
        assert config.cluster_id is None
        assert config.sync.enabled is True

        # Should print warning to stderr
        captured = capsys.readouterr()
        assert "Warning: Failed to parse" in captured.err
        assert "Using default configuration" in captured.err


class TestConfigValidate:
    """Tests for Config.validate() method."""

    def test_validate_cluster_id_missing(self) -> None:
        """Test validation fails when cluster_id is not set."""
        config = Config()
        errors = config.validate()
        assert len(errors) == 1
        assert "Cluster ID is not configured" in errors[0]

    def test_validate_cluster_id_set(self) -> None:
        """Test validation passes when cluster_id is set."""
        config = Config(cluster_id="test-cluster")
        errors = config.validate()
        assert len(errors) == 0

    def test_validate_max_size_mb_positive(self) -> None:
        """Test validation fails when max_size_mb is not positive."""
        config = Config(cluster_id="test-cluster")
        config.sync.max_size_mb = 0
        errors = config.validate()
        assert len(errors) == 1
        assert "max_size_mb must be a positive number" in errors[0]

        config.sync.max_size_mb = -1
        errors = config.validate()
        assert len(errors) == 1
        assert "max_size_mb must be a positive number" in errors[0]

    def test_validate_max_file_size_mb_positive(self) -> None:
        """Test validation fails when max_file_size_mb is not positive."""
        config = Config(cluster_id="test-cluster")
        config.sync.max_file_size_mb = 0
        errors = config.validate()
        assert len(errors) == 1
        assert "max_file_size_mb must be a positive number" in errors[0]

        config.sync.max_file_size_mb = -5
        errors = config.validate()
        assert len(errors) == 1
        assert "max_file_size_mb must be a positive number" in errors[0]

    def test_validate_multiple_errors(self) -> None:
        """Test validation returns multiple errors."""
        config = Config()  # cluster_id not set
        config.sync.max_size_mb = -1
        config.sync.max_file_size_mb = 0
        errors = config.validate()
        assert len(errors) == 3
        assert any("Cluster ID is not configured" in e for e in errors)
        assert any("max_size_mb" in e for e in errors)
        assert any("max_file_size_mb" in e for e in errors)

    def test_validate_positive_values_pass(self) -> None:
        """Test validation passes with positive size values."""
        config = Config(cluster_id="test-cluster")
        config.sync.max_size_mb = 100.0
        config.sync.max_file_size_mb = 10.0
        errors = config.validate()
        assert len(errors) == 0


class TestConfigLoadFromDatabrickscfg:
    """Tests for loading cluster_id from ~/.databrickscfg."""

    def test_load_from_databrickscfg_default_profile(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test loading cluster_id from DEFAULT profile."""
        databrickscfg = tmp_path / ".databrickscfg"
        databrickscfg.write_text("""
[DEFAULT]
host = https://test-workspace.cloud.databricks.com
token = dapi123
cluster_id = cfg-cluster-123
""")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DATABRICKS_CLUSTER_ID", raising=False)
        monkeypatch.delenv("DATABRICKS_CONFIG_PROFILE", raising=False)

        config = Config.load()
        assert config.cluster_id == "cfg-cluster-123"

    def test_load_from_databrickscfg_custom_profile(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test loading cluster_id from custom profile."""
        databrickscfg = tmp_path / ".databrickscfg"
        databrickscfg.write_text("""
[DEFAULT]
host = https://default-workspace.cloud.databricks.com
cluster_id = default-cluster

[DEVELOPMENT]
host = https://dev-workspace.cloud.databricks.com
cluster_id = dev-cluster-456
""")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DATABRICKS_CLUSTER_ID", raising=False)
        monkeypatch.setenv("DATABRICKS_CONFIG_PROFILE", "DEVELOPMENT")

        config = Config.load()
        assert config.cluster_id == "dev-cluster-456"

    def test_env_overrides_databrickscfg(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that env var takes priority over databrickscfg."""
        databrickscfg = tmp_path / ".databrickscfg"
        databrickscfg.write_text("""
[DEFAULT]
cluster_id = cfg-cluster-123
""")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("DATABRICKS_CLUSTER_ID", "env-cluster-override")

        config = Config.load()
        # Environment variable should take priority
        assert config.cluster_id == "env-cluster-override"

    def test_databrickscfg_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test when ~/.databrickscfg doesn't exist."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DATABRICKS_CLUSTER_ID", raising=False)

        config = Config.load()
        assert config.cluster_id is None

    def test_databrickscfg_profile_not_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test when specified profile doesn't exist."""
        databrickscfg = tmp_path / ".databrickscfg"
        databrickscfg.write_text("""
[DEFAULT]
cluster_id = default-cluster
""")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DATABRICKS_CLUSTER_ID", raising=False)
        monkeypatch.setenv("DATABRICKS_CONFIG_PROFILE", "NONEXISTENT")

        config = Config.load()
        # Profile not found, so cluster_id is None
        assert config.cluster_id is None

    def test_databrickscfg_no_cluster_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test when profile exists but has no cluster_id."""
        databrickscfg = tmp_path / ".databrickscfg"
        databrickscfg.write_text("""
[DEFAULT]
host = https://test-workspace.cloud.databricks.com
token = dapi123
""")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DATABRICKS_CLUSTER_ID", raising=False)
        monkeypatch.delenv("DATABRICKS_CONFIG_PROFILE", raising=False)

        config = Config.load()
        # No cluster_id in profile
        assert config.cluster_id is None

    def test_databrickscfg_invalid_format(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test when databrickscfg has invalid format."""
        databrickscfg = tmp_path / ".databrickscfg"
        # Write invalid INI content (missing section header)
        databrickscfg.write_text("cluster_id = invalid")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DATABRICKS_CLUSTER_ID", raising=False)

        config = Config.load()
        # Should use default (None) since parsing failed
        assert config.cluster_id is None

        # Should print warning to stderr
        captured = capsys.readouterr()
        assert "Warning: Failed to parse" in captured.err
        assert "Skipping databrickscfg configuration" in captured.err
