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


class TestParseDataUrl:
    """Tests for _parse_data_url method."""

    def test_parse_valid_data_url(self, mock_kernel: DatabricksKernel) -> None:
        """Test parsing a valid Data URL."""
        data_url = "data:image/png;base64,iVBORw0KGgo="
        mime_type, base64_data = mock_kernel._parse_data_url(data_url)

        assert mime_type == "image/png"
        assert base64_data == "iVBORw0KGgo="

    def test_parse_jpeg_data_url(self, mock_kernel: DatabricksKernel) -> None:
        """Test parsing a JPEG Data URL."""
        data_url = "data:image/jpeg;base64,/9j/4AAQ="
        mime_type, base64_data = mock_kernel._parse_data_url(data_url)

        assert mime_type == "image/jpeg"
        assert base64_data == "/9j/4AAQ="

    def test_parse_invalid_data_url(self, mock_kernel: DatabricksKernel) -> None:
        """Test parsing an invalid Data URL."""
        mime_type, base64_data = mock_kernel._parse_data_url("not-a-data-url")

        assert mime_type is None
        assert base64_data is None

    def test_parse_malformed_data_url(self, mock_kernel: DatabricksKernel) -> None:
        """Test parsing a malformed Data URL."""
        mime_type, base64_data = mock_kernel._parse_data_url("data:nocomma")

        assert mime_type is None
        assert base64_data is None


class TestGenerateHtmlTable:
    """Tests for _generate_html_table method."""

    def test_generate_table_with_schema(self, mock_kernel: DatabricksKernel) -> None:
        """Test generating an HTML table with schema."""
        data = [["val1", "val2"], ["val3", "val4"]]
        schema = [{"name": "col1"}, {"name": "col2"}]

        html = mock_kernel._generate_html_table(data, schema)

        assert '<table border="1" class="dataframe">' in html
        assert "<th>col1</th>" in html
        assert "<th>col2</th>" in html
        assert "<td>val1</td>" in html
        assert "<td>val4</td>" in html

    def test_generate_table_without_schema(self, mock_kernel: DatabricksKernel) -> None:
        """Test generating an HTML table without schema."""
        data = [["val1", "val2"]]

        html = mock_kernel._generate_html_table(data, None)

        assert "<thead>" not in html
        assert "<td>val1</td>" in html

    def test_generate_table_with_none_values(
        self, mock_kernel: DatabricksKernel
    ) -> None:
        """Test generating an HTML table with None values."""
        data = [[None, "val2"]]

        html = mock_kernel._generate_html_table(data, None)

        assert "<td></td>" in html
        assert "<td>val2</td>" in html

    def test_generate_table_escapes_html(self, mock_kernel: DatabricksKernel) -> None:
        """Test that HTML characters are escaped."""
        data = [["<script>alert('xss')</script>"]]

        html = mock_kernel._generate_html_table(data, None)

        assert "&lt;script&gt;" in html
        assert "<script>" not in html


class TestProgressDisplay:
    """Tests for progress display functionality."""

    def test_send_progress_marks_active(self, mock_kernel: DatabricksKernel) -> None:
        """Test that _send_progress marks progress as active."""
        assert mock_kernel._progress_display_id is None

        mock_kernel._send_progress("RUNNING", "RUNNING", 1.0)

        assert mock_kernel._progress_display_id is not None
        assert mock_kernel._progress_display_id.startswith("progress-")

    def test_send_progress_uses_display_data(
        self, mock_kernel: DatabricksKernel
    ) -> None:
        """Test that first _send_progress uses display_data with display_id."""
        mock_kernel._send_progress("RUNNING", "RUNNING", 1.0)

        # First call should use display_data
        calls = mock_kernel.send_response.call_args_list
        assert len(calls) == 1
        assert calls[0][0][1] == "display_data"
        content = calls[0][0][2]
        assert "transient" in content
        assert "display_id" in content["transient"]

    def test_send_progress_uses_update_display_data(
        self, mock_kernel: DatabricksKernel
    ) -> None:
        """Test that subsequent _send_progress uses update_display_data."""
        mock_kernel._send_progress("RUNNING", "RUNNING", 1.0)
        mock_kernel.send_response.reset_mock()
        mock_kernel._send_progress("RUNNING", "RUNNING", 2.0)

        # Second call should use update_display_data
        calls = mock_kernel.send_response.call_args_list
        assert len(calls) == 1
        assert calls[0][0][1] == "update_display_data"

    def test_send_progress_contains_spinner(
        self, mock_kernel: DatabricksKernel
    ) -> None:
        """Test that progress message contains spinner character."""
        from jupyter_databricks_kernel.kernel import SPINNER_CHARS

        mock_kernel._send_progress("RUNNING", "RUNNING", 1.0)

        # Get the display_data call
        call_args = mock_kernel.send_response.call_args_list[0][0]
        content = call_args[2]
        text = content["data"]["text/plain"]
        assert any(char in text for char in SPINNER_CHARS)

    def test_send_progress_contains_status(self, mock_kernel: DatabricksKernel) -> None:
        """Test that progress message contains cluster and command status."""
        mock_kernel._send_progress("RUNNING", "QUEUED", 5.0)

        # Get the display_data call
        call_args = mock_kernel.send_response.call_args_list[0][0]
        content = call_args[2]
        text = content["data"]["text/plain"]
        assert "RUNNING" in text
        assert "QUEUED" in text
        assert "5.0s" in text  # Time < 10s shows 1 decimal place

    def test_format_completion_text(self, mock_kernel: DatabricksKernel) -> None:
        """Test that _format_completion_text formats correctly."""
        text = mock_kernel._format_completion_text(5.5)
        assert "Cell executed" in text
        assert "5.5s" in text

    def test_format_completion_text_with_sync(
        self, mock_kernel: DatabricksKernel
    ) -> None:
        """Test that _format_completion_text includes sync info when set."""
        # Set sync info (normally set by _sync_files)
        mock_kernel._sync_info = "Synced 10 files in 2.5s"
        text = mock_kernel._format_completion_text(3.0)
        assert "Synced 10 files" in text
        assert "2.5s" in text
        assert "Cell executed" in text
        assert "3.0s" in text
        # Should have separator line
        assert "─" in text

    def test_execute_sends_progress(self, mock_kernel: DatabricksKernel) -> None:
        """Test that execute sends progress during execution."""
        mock_kernel._initialized = True
        mock_kernel.executor = MagicMock()
        mock_kernel.file_sync = MagicMock()
        mock_kernel.file_sync.needs_sync.return_value = False

        from jupyter_databricks_kernel.executor import ExecutionResult

        # Capture the on_progress callback
        captured_callback = None

        def capture_execute(code, on_progress=None):
            nonlocal captured_callback
            captured_callback = on_progress
            return ExecutionResult(status="ok", output="result")

        mock_kernel.executor.execute.side_effect = capture_execute

        asyncio.run(mock_kernel.do_execute("print(1)", silent=False))

        # Verify callback was passed
        assert captured_callback is not None

    def test_execute_silent_no_progress(self, mock_kernel: DatabricksKernel) -> None:
        """Test that silent execution does not send progress."""
        mock_kernel._initialized = True
        mock_kernel.executor = MagicMock()
        mock_kernel.file_sync = MagicMock()
        mock_kernel.file_sync.needs_sync.return_value = False

        from jupyter_databricks_kernel.executor import ExecutionResult

        captured_callback = None

        def capture_execute(code, on_progress=None):
            nonlocal captured_callback
            captured_callback = on_progress
            return ExecutionResult(status="ok")

        mock_kernel.executor.execute.side_effect = capture_execute

        asyncio.run(mock_kernel.do_execute("print(1)", silent=True))

        # Verify no callback was passed
        assert captured_callback is None


class TestDisplayResults:
    """Tests for displaying different result types."""

    def test_display_image_result(self, mock_kernel: DatabricksKernel) -> None:
        """Test that images are displayed via display_data."""
        mock_kernel._initialized = True
        mock_kernel.executor = MagicMock()
        mock_kernel.file_sync = MagicMock()
        mock_kernel.file_sync.needs_sync.return_value = False

        from jupyter_databricks_kernel.executor import ExecutionResult

        mock_kernel.executor.execute.return_value = ExecutionResult(
            status="ok",
            images=["data:image/png;base64,iVBORw0KGgo="],
        )

        asyncio.run(mock_kernel.do_execute("display(plt)", silent=False))

        # Check display_data was called
        calls = mock_kernel.send_response.call_args_list
        display_calls = [c for c in calls if c[0][1] == "display_data"]
        assert len(display_calls) == 1
        assert "image/png" in display_calls[0][0][2]["data"]

    def test_display_multiple_images(self, mock_kernel: DatabricksKernel) -> None:
        """Test that multiple images are displayed."""
        mock_kernel._initialized = True
        mock_kernel.executor = MagicMock()
        mock_kernel.file_sync = MagicMock()
        mock_kernel.file_sync.needs_sync.return_value = False

        from jupyter_databricks_kernel.executor import ExecutionResult

        mock_kernel.executor.execute.return_value = ExecutionResult(
            status="ok",
            images=[
                "data:image/png;base64,img1=",
                "data:image/png;base64,img2=",
            ],
        )

        asyncio.run(mock_kernel.do_execute("display(figs)", silent=False))

        calls = mock_kernel.send_response.call_args_list
        display_calls = [c for c in calls if c[0][1] == "display_data"]
        assert len(display_calls) == 2

    def test_display_table_result(self, mock_kernel: DatabricksKernel) -> None:
        """Test that tables are displayed as HTML."""
        mock_kernel._initialized = True
        mock_kernel.executor = MagicMock()
        mock_kernel.file_sync = MagicMock()
        mock_kernel.file_sync.needs_sync.return_value = False

        from jupyter_databricks_kernel.executor import ExecutionResult

        mock_kernel.executor.execute.return_value = ExecutionResult(
            status="ok",
            table_data=[["val1", "val2"]],
            table_schema=[{"name": "col1"}, {"name": "col2"}],
        )

        asyncio.run(mock_kernel.do_execute("df.show()", silent=False))

        calls = mock_kernel.send_response.call_args_list
        display_calls = [c for c in calls if c[0][1] == "display_data"]
        assert len(display_calls) == 1
        assert "text/html" in display_calls[0][0][2]["data"]

    def test_silent_mode_suppresses_display(
        self, mock_kernel: DatabricksKernel
    ) -> None:
        """Test that silent mode suppresses all output."""
        mock_kernel._initialized = True
        mock_kernel.executor = MagicMock()
        mock_kernel.file_sync = MagicMock()
        mock_kernel.file_sync.needs_sync.return_value = False

        from jupyter_databricks_kernel.executor import ExecutionResult

        mock_kernel.executor.execute.return_value = ExecutionResult(
            status="ok",
            output="text output",
            images=["data:image/png;base64,abc="],
            table_data=[["val"]],
        )

        asyncio.run(mock_kernel.do_execute("code", silent=True))

        # No output should be sent
        mock_kernel.send_response.assert_not_called()
