"""Tests for DatabricksExecutor."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from jupyter_databricks_kernel.executor import DatabricksExecutor, ExecutionResult


@pytest.fixture
def mock_config() -> MagicMock:
    """Create a mock config."""
    config = MagicMock()
    config.cluster_id = "test-cluster-id"
    return config


@pytest.fixture
def executor(mock_config: MagicMock) -> DatabricksExecutor:
    """Create an executor with mock config."""
    return DatabricksExecutor(mock_config)


class TestReconnect:
    """Tests for reconnect functionality."""

    def test_reconnect_destroys_old_context(self, executor: DatabricksExecutor) -> None:
        """Test that reconnect destroys the old context first."""
        executor.context_id = "old-context-id"

        with patch.object(executor, "destroy_context") as mock_destroy:
            with patch.object(executor, "create_context"):
                executor.reconnect()

        mock_destroy.assert_called_once()

    def test_reconnect_creates_new_context(self, executor: DatabricksExecutor) -> None:
        """Test that reconnect creates a new context."""
        executor.context_id = "old-context-id"

        with patch.object(executor, "destroy_context"):
            with patch.object(executor, "create_context") as mock_create:
                executor.reconnect()
                mock_create.assert_called_once()

    def test_reconnect_handles_destroy_error(
        self, executor: DatabricksExecutor
    ) -> None:
        """Test that reconnect continues even if destroy fails."""
        executor.context_id = "old-context-id"

        with patch.object(executor, "destroy_context") as mock_destroy:
            mock_destroy.side_effect = Exception("Context already gone")
            with patch.object(executor, "create_context") as mock_create:
                # Should not raise
                executor.reconnect()
                mock_create.assert_called_once()


class TestIsContextInvalidError:
    """Tests for _is_context_invalid_error method."""

    def test_detects_context_not_found(self, executor: DatabricksExecutor) -> None:
        """Test that 'context not found' errors are detected."""
        error = Exception("Context not found")
        assert executor._is_context_invalid_error(error) is True

    def test_detects_context_does_not_exist(self, executor: DatabricksExecutor) -> None:
        """Test that 'context does not exist' errors are detected."""
        error = Exception("Execution context does not exist")
        assert executor._is_context_invalid_error(error) is True

    def test_detects_invalid_context(self, executor: DatabricksExecutor) -> None:
        """Test that 'invalid context' errors are detected."""
        error = Exception("Invalid context ID provided")
        assert executor._is_context_invalid_error(error) is True

    def test_detects_context_expired(self, executor: DatabricksExecutor) -> None:
        """Test that 'context expired' errors are detected."""
        error = Exception("Execution context expired")
        assert executor._is_context_invalid_error(error) is True

    def test_detects_context_id_error(self, executor: DatabricksExecutor) -> None:
        """Test that context_id related errors are detected."""
        error = Exception("Error: context_id is invalid")
        assert executor._is_context_invalid_error(error) is True

    def test_ignores_network_errors(self, executor: DatabricksExecutor) -> None:
        """Test that network errors are not flagged as context invalid."""
        error = Exception("Network timeout")
        assert executor._is_context_invalid_error(error) is False

    def test_ignores_file_not_found(self, executor: DatabricksExecutor) -> None:
        """Test that file errors are not flagged as context invalid."""
        error = Exception("File not found: /path/to/file")
        assert executor._is_context_invalid_error(error) is False

    def test_ignores_variable_not_found(self, executor: DatabricksExecutor) -> None:
        """Test that variable errors are not flagged as context invalid."""
        error = Exception("NameError: name 'x' is not defined")
        assert executor._is_context_invalid_error(error) is False

    def test_ignores_invalid_argument(self, executor: DatabricksExecutor) -> None:
        """Test that argument errors are not flagged as context invalid."""
        error = Exception("Invalid argument: value must be positive")
        assert executor._is_context_invalid_error(error) is False

    def test_ignores_session_without_context(
        self, executor: DatabricksExecutor
    ) -> None:
        """Test that generic session errors without 'context' are ignored."""
        error = Exception("Session expired")
        assert executor._is_context_invalid_error(error) is False


class TestExecuteWithReconnect:
    """Tests for execute with reconnection logic."""

    def test_execute_success(self, executor: DatabricksExecutor) -> None:
        """Test successful execution without reconnection."""
        executor.context_id = "test-context"

        with patch.object(executor, "_execute_internal") as mock_exec:
            mock_exec.return_value = ExecutionResult(status="ok", output="result")
            result = executor.execute("print(1)")

        assert result.status == "ok"
        assert result.output == "result"
        assert result.reconnected is False

    def test_execute_reconnects_on_context_error(
        self, executor: DatabricksExecutor
    ) -> None:
        """Test that execution reconnects on context invalid error."""
        executor.context_id = "test-context"

        with patch.object(executor, "_execute_internal") as mock_exec:
            # First call raises context error, second succeeds
            mock_exec.side_effect = [
                Exception("Context not found"),
                ExecutionResult(status="ok", output="result"),
            ]
            with patch.object(executor, "reconnect") as mock_reconnect:
                result = executor.execute("print(1)")

        mock_reconnect.assert_called_once()
        assert result.status == "ok"
        assert result.reconnected is True

    def test_execute_no_reconnect_on_other_error(
        self, executor: DatabricksExecutor
    ) -> None:
        """Test that execution does not reconnect on non-context errors."""
        executor.context_id = "test-context"

        with patch.object(executor, "_execute_internal") as mock_exec:
            mock_exec.side_effect = Exception("Some other error")
            with patch.object(executor, "reconnect") as mock_reconnect:
                result = executor.execute("print(1)")

        mock_reconnect.assert_not_called()
        assert result.status == "error"
        assert "Some other error" in (result.error or "")

    def test_execute_respects_allow_reconnect_false(
        self, executor: DatabricksExecutor
    ) -> None:
        """Test that allow_reconnect=False prevents reconnection."""
        executor.context_id = "test-context"

        with patch.object(executor, "_execute_internal") as mock_exec:
            mock_exec.side_effect = Exception("Context not found")
            with patch.object(executor, "reconnect") as mock_reconnect:
                result = executor.execute("print(1)", allow_reconnect=False)

        mock_reconnect.assert_not_called()
        assert result.status == "error"

    def test_execute_returns_error_when_retry_also_fails(
        self, executor: DatabricksExecutor
    ) -> None:
        """Test that execution returns error when retry after reconnect also fails."""
        executor.context_id = "test-context"

        with patch.object(executor, "_execute_internal") as mock_exec:
            # Both calls fail with context error
            mock_exec.side_effect = [
                Exception("Context not found"),
                Exception("Context still not found after reconnect"),
            ]
            with patch.object(executor, "reconnect"):
                result = executor.execute("print(1)")

        assert result.status == "error"
        assert "Reconnection failed" in (result.error or "")
        assert result.reconnected is False


class TestExecutionResult:
    """Tests for ExecutionResult dataclass."""

    def test_default_reconnected_is_false(self) -> None:
        """Test that reconnected defaults to False."""
        result = ExecutionResult(status="ok")
        assert result.reconnected is False

    def test_reconnected_can_be_set(self) -> None:
        """Test that reconnected can be set to True."""
        result = ExecutionResult(status="ok", reconnected=True)
        assert result.reconnected is True


class TestEnsureClusterRunning:
    """Tests for _ensure_cluster_running method."""

    def test_starts_terminated_cluster(self, executor: DatabricksExecutor) -> None:
        """Test that a terminated cluster is started."""
        from databricks.sdk.service.compute import State

        mock_client = MagicMock()
        mock_cluster = MagicMock()
        mock_cluster.state = State.TERMINATED

        mock_client.clusters.get.return_value = mock_cluster
        executor.client = mock_client

        executor._ensure_cluster_running()

        mock_client.clusters.start.assert_called_once_with("test-cluster-id")
        mock_client.clusters.wait_get_cluster_running.assert_called_once_with(
            "test-cluster-id"
        )

    def test_does_nothing_when_cluster_running(
        self, executor: DatabricksExecutor
    ) -> None:
        """Test that no action is taken when cluster is already running."""
        from databricks.sdk.service.compute import State

        mock_client = MagicMock()
        mock_cluster = MagicMock()
        mock_cluster.state = State.RUNNING

        mock_client.clusters.get.return_value = mock_cluster
        executor.client = mock_client

        executor._ensure_cluster_running()

        mock_client.clusters.start.assert_not_called()
        mock_client.clusters.wait_get_cluster_running.assert_not_called()

    def test_does_nothing_without_cluster_id(self, mock_config: MagicMock) -> None:
        """Test that no action is taken when cluster_id is not configured."""
        mock_config.cluster_id = None
        executor = DatabricksExecutor(mock_config)

        mock_client = MagicMock()
        executor.client = mock_client

        executor._ensure_cluster_running()

        mock_client.clusters.get.assert_not_called()
