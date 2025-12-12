"""Tests for DatabricksExecutor."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from jupyter_databricks_kernel.executor import DatabricksExecutor, ExecutionResult


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


class TestImageProcessing:
    """Tests for image processing methods."""

    def test_process_image_data_url(self, executor: DatabricksExecutor) -> None:
        """Test that Data URLs are returned unchanged."""
        data_url = "data:image/png;base64,iVBORw0KGgo="
        result = executor._process_image(data_url)
        assert result == data_url

    def test_process_image_filestore_path(self, executor: DatabricksExecutor) -> None:
        """Test that FileStore paths trigger download."""
        from io import BytesIO

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.contents = BytesIO(b"\x89PNG\r\n\x1a\n")
        mock_client.files.download.return_value = mock_response
        executor.client = mock_client

        result = executor._process_image("/plots/test.png")

        assert result is not None
        assert result.startswith("data:image/png;base64,")
        mock_client.files.download.assert_called_once_with("/FileStore/plots/test.png")

    def test_process_image_download_failure(self, executor: DatabricksExecutor) -> None:
        """Test that download failure returns None."""
        mock_client = MagicMock()
        mock_client.files.download.side_effect = Exception("Download failed")
        executor.client = mock_client

        result = executor._process_image("/plots/test.png")

        assert result is None

    def test_get_mime_type_png(self, executor: DatabricksExecutor) -> None:
        """Test MIME type detection for PNG."""
        assert executor._get_mime_type("/path/to/image.png") == "image/png"

    def test_get_mime_type_jpeg(self, executor: DatabricksExecutor) -> None:
        """Test MIME type detection for JPEG."""
        assert executor._get_mime_type("/path/to/image.jpg") == "image/jpeg"
        assert executor._get_mime_type("/path/to/image.jpeg") == "image/jpeg"

    def test_get_mime_type_gif(self, executor: DatabricksExecutor) -> None:
        """Test MIME type detection for GIF."""
        assert executor._get_mime_type("/path/to/image.gif") == "image/gif"

    def test_get_mime_type_svg(self, executor: DatabricksExecutor) -> None:
        """Test MIME type detection for SVG."""
        assert executor._get_mime_type("/path/to/image.svg") == "image/svg+xml"

    def test_get_mime_type_unknown(self, executor: DatabricksExecutor) -> None:
        """Test MIME type defaults to PNG for unknown extensions."""
        assert executor._get_mime_type("/path/to/file") == "image/png"
        assert executor._get_mime_type("/path/to/file.xyz") == "image/png"


class TestExecutionResultTypes:
    """Tests for different result types in _execute_internal."""

    def test_image_result_type(self, executor: DatabricksExecutor) -> None:
        """Test IMAGE result type processing."""
        from databricks.sdk.service.compute import ResultType

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_results = MagicMock()
        mock_results.cause = None
        mock_results.result_type = ResultType.IMAGE
        mock_results.file_name = "data:image/png;base64,iVBORw0KGgo="
        mock_results.data = None
        mock_response.status = "Finished"
        mock_response.results = mock_results
        mock_client.command_execution.execute.return_value.result.return_value = (
            mock_response
        )
        executor.client = mock_client
        executor.context_id = "test-context"

        result = executor._execute_internal("display(plt)")

        assert result.status == "ok"
        assert result.images is not None
        assert len(result.images) == 1
        assert result.images[0] == "data:image/png;base64,iVBORw0KGgo="

    def test_images_result_type(self, executor: DatabricksExecutor) -> None:
        """Test IMAGES result type processing."""
        from databricks.sdk.service.compute import ResultType

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_results = MagicMock()
        mock_results.cause = None
        mock_results.result_type = ResultType.IMAGES
        mock_results.file_names = [
            "data:image/png;base64,img1=",
            "data:image/png;base64,img2=",
        ]
        mock_results.data = None
        mock_response.status = "Finished"
        mock_response.results = mock_results
        mock_client.command_execution.execute.return_value.result.return_value = (
            mock_response
        )
        executor.client = mock_client
        executor.context_id = "test-context"

        result = executor._execute_internal("display(fig)")

        assert result.status == "ok"
        assert result.images is not None
        assert len(result.images) == 2

    def test_table_result_type(self, executor: DatabricksExecutor) -> None:
        """Test TABLE result type processing."""
        from databricks.sdk.service.compute import ResultType

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_results = MagicMock()
        mock_results.cause = None
        mock_results.result_type = ResultType.TABLE
        mock_results.data = [["val1", "val2"], ["val3", "val4"]]
        mock_results.schema = [{"name": "col1"}, {"name": "col2"}]
        mock_response.status = "Finished"
        mock_response.results = mock_results
        mock_client.command_execution.execute.return_value.result.return_value = (
            mock_response
        )
        executor.client = mock_client
        executor.context_id = "test-context"

        result = executor._execute_internal("df.show()")

        assert result.status == "ok"
        assert result.table_data == [["val1", "val2"], ["val3", "val4"]]
        assert result.table_schema == [{"name": "col1"}, {"name": "col2"}]

    def test_text_result_type(self, executor: DatabricksExecutor) -> None:
        """Test TEXT result type processing."""
        from databricks.sdk.service.compute import ResultType

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_results = MagicMock()
        mock_results.cause = None
        mock_results.result_type = ResultType.TEXT
        mock_results.data = "Hello, World!"
        mock_results.file_name = None
        mock_results.file_names = None
        mock_results.schema = None
        mock_response.status = "Finished"
        mock_response.results = mock_results
        mock_client.command_execution.execute.return_value.result.return_value = (
            mock_response
        )
        executor.client = mock_client
        executor.context_id = "test-context"

        result = executor._execute_internal("print('Hello, World!')")

        assert result.status == "ok"
        assert result.output == "Hello, World!"


class TestGetClusterState:
    """Tests for get_cluster_state method."""

    def test_returns_cluster_state(self, executor: DatabricksExecutor) -> None:
        """Test that cluster state is returned correctly."""
        from databricks.sdk.service.compute import State

        mock_client = MagicMock()
        mock_cluster = MagicMock()
        mock_cluster.state = State.RUNNING
        mock_client.clusters.get.return_value = mock_cluster
        executor.client = mock_client

        state = executor.get_cluster_state()

        assert state == "RUNNING"

    def test_returns_unknown_without_cluster_id(self, mock_config: MagicMock) -> None:
        """Test that UNKNOWN is returned when cluster_id is not set."""
        mock_config.cluster_id = None
        executor = DatabricksExecutor(mock_config)

        state = executor.get_cluster_state()

        assert state == "UNKNOWN"

    def test_returns_unknown_on_error(self, executor: DatabricksExecutor) -> None:
        """Test that UNKNOWN is returned on error."""
        mock_client = MagicMock()
        mock_client.clusters.get.side_effect = Exception("API error")
        executor.client = mock_client

        state = executor.get_cluster_state()

        assert state == "UNKNOWN"


class TestExecuteWithPolling:
    """Tests for _execute_with_polling method."""

    def test_calls_progress_callback(self, executor: DatabricksExecutor) -> None:
        """Test that progress callback is called during execution."""
        from databricks.sdk.service.compute import CommandStatus, State

        mock_client = MagicMock()

        # Mock cluster state
        mock_cluster = MagicMock()
        mock_cluster.state = State.RUNNING
        mock_client.clusters.get.return_value = mock_cluster

        # Mock execute to return a waiter with command_id
        mock_waiter = MagicMock()
        mock_waiter.command_id = "test-command-id"
        mock_client.command_execution.execute.return_value = mock_waiter

        # Mock command_status to return FINISHED on first call
        mock_status_response = MagicMock()
        mock_status_response.status = CommandStatus.FINISHED
        mock_status_response.results = MagicMock()
        mock_status_response.results.cause = None
        mock_status_response.results.result_type = None
        mock_status_response.results.data = "result"
        mock_client.command_execution.command_status.return_value = mock_status_response

        executor.client = mock_client
        executor.context_id = "test-context"

        progress_calls: list[tuple[str, str, float]] = []

        def on_progress(cs: str, cmd: str, elapsed: float) -> None:
            progress_calls.append((cs, cmd, elapsed))

        result = executor._execute_with_polling("print(1)", on_progress)

        assert result.status == "ok"
        assert len(progress_calls) == 1
        assert progress_calls[0][0] == "RUNNING"
        assert progress_calls[0][1] == "FINISHED"

    def test_polls_until_finished(self, executor: DatabricksExecutor) -> None:
        """Test that polling continues until command finishes."""
        from databricks.sdk.service.compute import CommandStatus, State

        mock_client = MagicMock()

        # Mock cluster state
        mock_cluster = MagicMock()
        mock_cluster.state = State.RUNNING
        mock_client.clusters.get.return_value = mock_cluster

        # Mock execute
        mock_waiter = MagicMock()
        mock_waiter.command_id = "test-command-id"
        mock_client.command_execution.execute.return_value = mock_waiter

        # Mock command_status to return RUNNING twice, then FINISHED
        mock_running_response = MagicMock()
        mock_running_response.status = CommandStatus.RUNNING
        mock_running_response.results = None

        mock_finished_response = MagicMock()
        mock_finished_response.status = CommandStatus.FINISHED
        mock_finished_response.results = MagicMock()
        mock_finished_response.results.cause = None
        mock_finished_response.results.result_type = None
        mock_finished_response.results.data = "result"

        mock_client.command_execution.command_status.side_effect = [
            mock_running_response,
            mock_running_response,
            mock_finished_response,
        ]

        executor.client = mock_client
        executor.context_id = "test-context"

        progress_calls: list[tuple[str, str]] = []

        def on_progress(cs: str, cmd: str, elapsed: float) -> None:
            progress_calls.append((cs, cmd))

        with patch("jupyter_databricks_kernel.executor.time.sleep"):
            with patch(
                "jupyter_databricks_kernel.executor.API_POLL_INTERVAL_SECONDS", 0
            ):
                result = executor._execute_with_polling("print(1)", on_progress)

        assert result.status == "ok"
        # Progress should have been called multiple times
        assert len(progress_calls) >= 3
        # First calls should show RUNNING status (uppercase)
        assert progress_calls[0][1] == "RUNNING"
        # Last call should show FINISHED status (uppercase)
        assert progress_calls[-1][1] == "FINISHED"

    def test_execute_uses_polling_with_callback(
        self, executor: DatabricksExecutor
    ) -> None:
        """Test that execute uses polling when on_progress is provided."""
        executor.context_id = "test-context"

        with patch.object(executor, "_execute_with_polling") as mock_polling:
            mock_polling.return_value = ExecutionResult(status="ok")

            def callback(c: str, s: str, e: float) -> None:
                pass

            executor.execute("print(1)", on_progress=callback)

        mock_polling.assert_called_once()

    def test_execute_uses_internal_without_callback(
        self, executor: DatabricksExecutor
    ) -> None:
        """Test that execute uses _execute_internal when no callback."""
        executor.context_id = "test-context"

        with patch.object(executor, "_execute_internal") as mock_internal:
            mock_internal.return_value = ExecutionResult(status="ok")
            executor.execute("print(1)")

        mock_internal.assert_called_once()


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


class TestTimeoutHandling:
    """Tests for timeout error handling using shared fixture."""

    def test_execute_returns_error_on_timeout(
        self,
        mock_config: MagicMock,
        mock_client_timeout: MagicMock,
    ) -> None:
        """Test that timeout errors are returned as error results."""
        executor = DatabricksExecutor(mock_config, client=mock_client_timeout)
        executor.context_id = "test-context"

        # Use execute() which catches exceptions and returns error results
        result = executor.execute("long_running_code()")

        assert result.status == "error"
        assert "timed out" in (result.error or "").lower()


class TestClusterStateWithFixture:
    """Tests for cluster state handling using shared fixture."""

    def test_starts_terminated_cluster_with_fixture(
        self,
        mock_config: MagicMock,
        mock_client_cluster_terminated: MagicMock,
    ) -> None:
        """Test that terminated cluster is started using shared fixture."""
        executor = DatabricksExecutor(
            mock_config, client=mock_client_cluster_terminated
        )

        executor._ensure_cluster_running()

        mock_client_cluster_terminated.clusters.start.assert_called_once_with(
            "test-cluster-id"
        )
        mock_client_cluster_terminated.clusters.wait_get_cluster_running.assert_called_once_with(
            "test-cluster-id"
        )
