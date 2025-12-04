"""Tests for DatabricksKernel."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from jupyter_databricks_kernel.kernel import DatabricksKernel


@pytest.fixture
def mock_kernel() -> DatabricksKernel:
    """Create a kernel with mocked dependencies."""
    with patch("jupyter_databricks_kernel.kernel.Config") as mock_config_class:
        mock_config = MagicMock()
        mock_config.validate.return_value = []
        mock_config.cluster_id = "test-cluster"
        mock_config_class.load.return_value = mock_config

        kernel = DatabricksKernel()
        kernel.iopub_socket = MagicMock()
        kernel.send_response = MagicMock()
        kernel.execution_count = 1
        return kernel


class TestSessionIdManagement:
    """Tests for session ID management."""

    def test_session_id_generated_on_init(self, mock_kernel: DatabricksKernel) -> None:
        """Test that session ID is generated on initialization."""
        assert mock_kernel._session_id is not None
        assert len(mock_kernel._session_id) == 8

    def test_session_id_is_unique(self) -> None:
        """Test that each kernel instance gets a unique session ID."""
        with patch("jupyter_databricks_kernel.kernel.Config") as mock_config_class:
            mock_config = MagicMock()
            mock_config.validate.return_value = []
            mock_config_class.load.return_value = mock_config

            kernel1 = DatabricksKernel()
            kernel2 = DatabricksKernel()

        assert kernel1._session_id != kernel2._session_id


class TestRestartBehavior:
    """Tests for kernel restart behavior."""

    def test_shutdown_restart_keeps_executor(
        self, mock_kernel: DatabricksKernel
    ) -> None:
        """Test that restart=True keeps the executor."""
        mock_kernel.executor = MagicMock()
        mock_kernel.file_sync = MagicMock()
        mock_kernel._initialized = True

        result = asyncio.run(mock_kernel.do_shutdown(restart=True))

        assert result["status"] == "ok"
        assert result["restart"] is True
        # Executor should NOT be destroyed on restart
        assert mock_kernel.executor is not None
        mock_kernel.executor.destroy_context.assert_not_called()

    def test_shutdown_no_restart_destroys_executor(
        self, mock_kernel: DatabricksKernel
    ) -> None:
        """Test that restart=False destroys the executor."""
        mock_kernel.executor = MagicMock()
        mock_kernel.file_sync = MagicMock()
        mock_kernel._initialized = True

        result = asyncio.run(mock_kernel.do_shutdown(restart=False))

        assert result["status"] == "ok"
        assert result["restart"] is False
        # Executor should be destroyed on full shutdown
        assert mock_kernel.executor is None

    def test_shutdown_restart_resets_initialized_flag(
        self, mock_kernel: DatabricksKernel
    ) -> None:
        """Test that restart resets the initialized flag."""
        mock_kernel._initialized = True

        asyncio.run(mock_kernel.do_shutdown(restart=True))

        assert mock_kernel._initialized is False

    def test_initialize_reuses_existing_executor(
        self, mock_kernel: DatabricksKernel
    ) -> None:
        """Test that _initialize reuses existing executor after restart."""
        # Setup: create executor and file_sync, then simulate restart
        original_executor = MagicMock()
        original_file_sync = MagicMock()
        mock_kernel.executor = original_executor
        mock_kernel.file_sync = original_file_sync
        mock_kernel._initialized = False  # Simulates post-restart state

        # Act: re-initialize
        result = mock_kernel._initialize()

        # Assert: same instances are reused
        assert result is True
        assert mock_kernel.executor is original_executor
        assert mock_kernel.file_sync is original_file_sync

    def test_restart_does_not_call_file_sync_cleanup(
        self, mock_kernel: DatabricksKernel
    ) -> None:
        """Test that restart=True does not call file_sync.cleanup()."""
        mock_kernel.executor = MagicMock()
        mock_kernel.file_sync = MagicMock()
        mock_kernel._initialized = True

        asyncio.run(mock_kernel.do_shutdown(restart=True))

        mock_kernel.file_sync.cleanup.assert_not_called()


class TestReconnectionHandling:
    """Tests for reconnection handling."""

    def test_handle_reconnection_notifies_user(
        self, mock_kernel: DatabricksKernel
    ) -> None:
        """Test that reconnection notifies the user."""
        mock_kernel.executor = MagicMock()
        mock_kernel.file_sync = MagicMock()
        mock_kernel._last_dbfs_path = "/tmp/test/path"

        mock_kernel._handle_reconnection()

        mock_kernel.send_response.assert_called()
        call_args = mock_kernel.send_response.call_args_list[0]
        assert "reconnected" in call_args[0][2]["text"].lower()

    def test_handle_reconnection_reruns_setup_code(
        self, mock_kernel: DatabricksKernel
    ) -> None:
        """Test that reconnection re-runs setup code."""
        from jupyter_databricks_kernel.executor import ExecutionResult

        mock_kernel.executor = MagicMock()
        mock_kernel.executor.execute.return_value = ExecutionResult(status="ok")
        mock_kernel.file_sync = MagicMock()
        mock_kernel.file_sync.get_setup_code.return_value = "setup_code"
        mock_kernel._last_dbfs_path = "/tmp/test/path"

        mock_kernel._handle_reconnection()

        mock_kernel.file_sync.get_setup_code.assert_called_once_with("/tmp/test/path")
        mock_kernel.executor.execute.assert_called_once_with(
            "setup_code", allow_reconnect=False
        )

    def test_handle_reconnection_warns_on_setup_error(
        self, mock_kernel: DatabricksKernel
    ) -> None:
        """Test that reconnection warns user if setup code fails."""
        from jupyter_databricks_kernel.executor import ExecutionResult

        mock_kernel.executor = MagicMock()
        mock_kernel.executor.execute.return_value = ExecutionResult(
            status="error", error="Setup failed"
        )
        mock_kernel.file_sync = MagicMock()
        mock_kernel.file_sync.get_setup_code.return_value = "setup_code"
        mock_kernel._last_dbfs_path = "/tmp/test/path"

        mock_kernel._handle_reconnection()

        # Check warning was sent
        calls = mock_kernel.send_response.call_args_list
        warning_sent = any("failed to restore" in str(c).lower() for c in calls)
        assert warning_sent

    def test_handle_reconnection_warns_on_exception(
        self, mock_kernel: DatabricksKernel
    ) -> None:
        """Test that reconnection warns user if setup throws exception."""
        mock_kernel.executor = MagicMock()
        mock_kernel.executor.execute.side_effect = Exception("Network error")
        mock_kernel.file_sync = MagicMock()
        mock_kernel.file_sync.get_setup_code.return_value = "setup_code"
        mock_kernel._last_dbfs_path = "/tmp/test/path"

        # Should not raise
        mock_kernel._handle_reconnection()

        # Check warning was sent
        calls = mock_kernel.send_response.call_args_list
        warning_sent = any("failed to restore" in str(c).lower() for c in calls)
        assert warning_sent

    def test_handle_reconnection_without_sync_path(
        self, mock_kernel: DatabricksKernel
    ) -> None:
        """Test reconnection when no sync path exists."""
        mock_kernel.executor = MagicMock()
        mock_kernel.file_sync = MagicMock()
        mock_kernel._last_dbfs_path = None

        # Should not raise
        mock_kernel._handle_reconnection()

        # Setup code should not be called
        mock_kernel.file_sync.get_setup_code.assert_not_called()


class TestExecuteWithReconnection:
    """Tests for execute with reconnection flag."""

    def test_execute_handles_reconnection_flag(
        self, mock_kernel: DatabricksKernel
    ) -> None:
        """Test that execute handles the reconnected flag."""
        mock_kernel._initialized = True
        mock_kernel.executor = MagicMock()
        mock_kernel.file_sync = MagicMock()
        mock_kernel.file_sync.needs_sync.return_value = False

        # Mock executor to return a result with reconnected=True
        from jupyter_databricks_kernel.executor import ExecutionResult

        mock_kernel.executor.execute.return_value = ExecutionResult(
            status="ok", output="result", reconnected=True
        )

        with patch.object(mock_kernel, "_handle_reconnection") as mock_handle:
            result = asyncio.run(mock_kernel.do_execute("print(1)", silent=False))

        mock_handle.assert_called_once()
        assert result["status"] == "ok"
