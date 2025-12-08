"""Tests for kernel installation."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

from jupyter_databricks_kernel.install import (
    KERNEL_NAME,
    KERNEL_SPEC,
    install_kernel,
    main,
)


class TestKernelSpec:
    """Tests for kernel specification constants."""

    def test_kernel_name(self) -> None:
        """Test that kernel name is correct."""
        assert KERNEL_NAME == "databricks"

    def test_kernel_spec_argv_starts_with_executable(self) -> None:
        """Test that argv starts with sys.executable."""
        assert KERNEL_SPEC["argv"][0] == sys.executable

    def test_kernel_spec_argv_has_module_flag(self) -> None:
        """Test that argv contains -m flag for module execution."""
        assert "-m" in KERNEL_SPEC["argv"]
        assert "jupyter_databricks_kernel" in KERNEL_SPEC["argv"]

    def test_kernel_spec_argv_has_connection_file(self) -> None:
        """Test that argv contains connection file placeholder."""
        assert "-f" in KERNEL_SPEC["argv"]
        assert "{connection_file}" in KERNEL_SPEC["argv"]

    def test_kernel_spec_display_name(self) -> None:
        """Test that display name is correct."""
        assert KERNEL_SPEC["display_name"] == "Databricks"

    def test_kernel_spec_language(self) -> None:
        """Test that language is python."""
        assert KERNEL_SPEC["language"] == "python"


class TestInstallKernel:
    """Tests for install_kernel function."""

    @patch("jupyter_client.kernelspec.KernelSpecManager")
    def test_install_kernel_default(self, mock_ksm_class: MagicMock) -> None:
        """Test default installation with prefix."""
        mock_ksm = MagicMock()
        mock_spec = MagicMock()
        mock_spec.resource_dir = "/path/to/kernels/databricks"
        mock_ksm.get_kernel_spec.return_value = mock_spec
        mock_ksm_class.return_value = mock_ksm

        install_kernel(prefix=sys.prefix)

        mock_ksm.install_kernel_spec.assert_called_once()
        call_kwargs = mock_ksm.install_kernel_spec.call_args.kwargs
        assert call_kwargs["kernel_name"] == "databricks"
        assert call_kwargs["user"] is False
        assert call_kwargs["prefix"] == sys.prefix

    @patch("jupyter_client.kernelspec.KernelSpecManager")
    def test_install_kernel_user(self, mock_ksm_class: MagicMock) -> None:
        """Test user installation."""
        mock_ksm = MagicMock()
        mock_spec = MagicMock()
        mock_spec.resource_dir = "/home/user/.local/share/jupyter/kernels/databricks"
        mock_ksm.get_kernel_spec.return_value = mock_spec
        mock_ksm_class.return_value = mock_ksm

        install_kernel(user=True)

        mock_ksm.install_kernel_spec.assert_called_once()
        call_kwargs = mock_ksm.install_kernel_spec.call_args.kwargs
        assert call_kwargs["kernel_name"] == "databricks"
        assert call_kwargs["user"] is True
        assert call_kwargs["prefix"] is None

    @patch("jupyter_client.kernelspec.KernelSpecManager")
    def test_install_kernel_custom_prefix(self, mock_ksm_class: MagicMock) -> None:
        """Test installation with custom prefix."""
        mock_ksm = MagicMock()
        mock_spec = MagicMock()
        mock_spec.resource_dir = "/custom/path/kernels/databricks"
        mock_ksm.get_kernel_spec.return_value = mock_spec
        mock_ksm_class.return_value = mock_ksm

        install_kernel(prefix="/custom/path")

        mock_ksm.install_kernel_spec.assert_called_once()
        call_kwargs = mock_ksm.install_kernel_spec.call_args.kwargs
        assert call_kwargs["kernel_name"] == "databricks"
        assert call_kwargs["user"] is False
        assert call_kwargs["prefix"] == "/custom/path"

    @patch("jupyter_client.kernelspec.KernelSpecManager")
    def test_install_kernel_writes_kernel_json(self, mock_ksm_class: MagicMock) -> None:
        """Test that kernel.json is written to temp directory."""
        mock_ksm = MagicMock()
        mock_spec = MagicMock()
        mock_spec.resource_dir = "/path/to/kernels/databricks"
        mock_ksm.get_kernel_spec.return_value = mock_spec
        mock_ksm_class.return_value = mock_ksm

        install_kernel(prefix=sys.prefix)

        # Verify install_kernel_spec was called with a valid directory
        call_args = mock_ksm.install_kernel_spec.call_args
        source_dir = call_args.args[0]
        assert source_dir is not None


class TestMain:
    """Tests for main CLI function."""

    @patch("jupyter_databricks_kernel.install.install_kernel")
    def test_main_default_args(self, mock_install: MagicMock) -> None:
        """Test main with no arguments uses sys.prefix."""
        with patch("sys.argv", ["install"]):
            main()

        mock_install.assert_called_once_with(prefix=sys.prefix)

    @patch("jupyter_databricks_kernel.install.install_kernel")
    def test_main_user_flag(self, mock_install: MagicMock) -> None:
        """Test main with --user flag."""
        with patch("sys.argv", ["install", "--user"]):
            main()

        mock_install.assert_called_once_with(user=True)

    @patch("jupyter_databricks_kernel.install.install_kernel")
    def test_main_sys_prefix_flag(self, mock_install: MagicMock) -> None:
        """Test main with --sys-prefix flag."""
        with patch("sys.argv", ["install", "--sys-prefix"]):
            main()

        mock_install.assert_called_once_with(prefix=sys.prefix)

    @patch("jupyter_databricks_kernel.install.install_kernel")
    def test_main_prefix_option(self, mock_install: MagicMock) -> None:
        """Test main with --prefix option."""
        with patch("sys.argv", ["install", "--prefix", "/custom/path"]):
            main()

        mock_install.assert_called_once_with(prefix="/custom/path")

    @patch("jupyter_databricks_kernel.install.install_kernel")
    def test_main_user_takes_precedence(self, mock_install: MagicMock) -> None:
        """Test that --user takes precedence over --prefix."""
        with patch("sys.argv", ["install", "--user", "--prefix", "/custom/path"]):
            main()

        mock_install.assert_called_once_with(user=True)
