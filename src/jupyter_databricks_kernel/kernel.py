"""Databricks Session Kernel for Jupyter."""

from __future__ import annotations

import html
import logging
import threading
import time
import uuid
from typing import Any

from ipykernel.kernelbase import Kernel

from . import __version__
from .config import Config
from .executor import DatabricksExecutor
from .sync import FileSync

logger = logging.getLogger(__name__)

# Spinner characters for progress animation
SPINNER_CHARS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class DatabricksKernel(Kernel):
    """Jupyter kernel that executes code on a remote Databricks cluster."""

    implementation = "databricks-session-kernel"
    implementation_version = __version__
    language = "python"
    language_version = "3.11"
    language_info = {
        "name": "python",
        "mimetype": "text/x-python",
        "file_extension": ".py",
    }
    banner = "Databricks Session Kernel - Execute Python on Databricks clusters"

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the Databricks kernel."""
        super().__init__(**kwargs)
        self._kernel_config = Config.load()
        self._session_id = str(uuid.uuid4())[:8]
        self.executor: DatabricksExecutor | None = None
        self.file_sync: FileSync | None = None
        self._initialized = False
        self._last_dbfs_path: str | None = None
        self._spinner_index = 0
        self._progress_display_id: str | None = None
        self._driver_logs_url: str | None = None
        # Track sync info for display during cell execution
        self._sync_info: str | None = None
        logger.info("Kernel initialized: session_id=%s", self._session_id)

    def _initialize(self) -> bool:
        """Initialize the Databricks connection.

        Returns:
            True if initialization succeeded, False otherwise.
        """
        if self._initialized:
            return True

        logger.debug("Initializing Databricks connection")

        # Validate configuration
        errors = self._kernel_config.validate()
        if errors:
            logger.error("Configuration validation failed: %s", errors)
            for error in errors:
                self.send_response(
                    self.iopub_socket,
                    "stream",
                    {"name": "stderr", "text": f"Configuration error: {error}\n"},
                )
            return False

        # Initialize executor and file sync (reuse existing if available)
        if self.executor is None:
            self.executor = DatabricksExecutor(self._kernel_config)
            # Cache driver logs URL
            self._driver_logs_url = self.executor.get_driver_logs_url()
        if self.file_sync is None:
            self.file_sync = FileSync(self._kernel_config, self._session_id)
        self._initialized = True
        logger.info(
            "Databricks connection initialized: cluster_id=%s",
            self._kernel_config.cluster_id,
        )
        return True

    def _send_sync_progress(self, message: str) -> None:
        """Send sync progress update to the frontend with spinner animation.

        Uses display_data with display_id for in-place updates.

        Args:
            message: Progress message to display.
        """
        spinner = SPINNER_CHARS[self._spinner_index % len(SPINNER_CHARS)]
        self._spinner_index += 1

        progress_text = f"{spinner} {message}"

        # Use display_id for in-place updates (same as _send_progress)
        # Include execution_count to make ID unique per cell execution
        if not self._progress_display_id:
            self._progress_display_id = f"progress-{self.execution_count}"
            self.send_response(
                self.iopub_socket,
                "display_data",
                {
                    "data": {"text/plain": progress_text},
                    "metadata": {},
                    "transient": {"display_id": self._progress_display_id},
                },
            )
        else:
            self.send_response(
                self.iopub_socket,
                "update_display_data",
                {
                    "data": {"text/plain": progress_text},
                    "metadata": {},
                    "transient": {"display_id": self._progress_display_id},
                },
            )

    def _run_with_spinner(
        self,
        message: str,
        func: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Run a function while displaying a spinner animation.

        Args:
            message: Message to display with spinner.
            func: Function to execute.
            *args: Positional arguments for the function.
            **kwargs: Keyword arguments for the function.

        Returns:
            The return value of the function.
        """
        result: Any = None
        error: BaseException | None = None
        done = threading.Event()

        def worker() -> None:
            nonlocal result, error
            try:
                result = func(*args, **kwargs)
            except BaseException as e:
                error = e
            finally:
                done.set()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        # Update spinner while waiting
        while not done.is_set():
            self._send_sync_progress(message)
            done.wait(timeout=0.1)

        thread.join()

        if error is not None:
            raise error
        return result

    def _sync_files(self) -> tuple[bool, float, int]:
        """Synchronize files if needed.

        Returns:
            Tuple of (success, sync_elapsed_seconds, file_count).
            If sync was skipped, returns (True, 0.0, 0).
        """
        if self.file_sync is None or self.executor is None:
            return True, 0.0, 0

        if not self.file_sync.needs_sync():
            logger.debug("File sync skipped: no changes detected")
            return True, 0.0, 0

        try:
            logger.debug("Starting file sync")
            sync_start = time.time()

            # Total steps: 4 local + 4 remote = 8
            total_steps = 8

            # Define progress callback with step info
            def sync_progress(message: str) -> None:
                # Prepend step info based on message content
                if "Collecting" in message:
                    step_msg = f"[1/{total_steps}] {message}"
                elif "Hashing" in message:
                    step_msg = f"[2/{total_steps}] {message}"
                elif "Creating" in message:
                    step_msg = f"[3/{total_steps}] {message}"
                elif "Uploading" in message:
                    step_msg = f"[4/{total_steps}] {message}"
                else:
                    step_msg = message
                self._send_sync_progress(step_msg)

            # Upload files with progress callback
            stats = self.file_sync.sync(on_progress=sync_progress)
            self._last_dbfs_path = stats.dbfs_path

            # Execute setup steps on remote with progress
            setup_steps = self.file_sync.get_setup_steps(stats.dbfs_path)
            for i, (description, code) in enumerate(setup_steps):
                step_num = 5 + i  # Steps 5-8
                result = self._run_with_spinner(
                    f"[{step_num}/{total_steps}] {description}...",
                    self.executor.execute,
                    code,
                    allow_reconnect=False,
                )

                if result.status != "ok":
                    err_msg = f"Setup failed at '{description}': {result.error}\n"
                    self.send_response(
                        self.iopub_socket,
                        "stream",
                        {"name": "stderr", "text": err_msg},
                    )
                    return False, 0.0, 0

            sync_elapsed = time.time() - sync_start
            logger.debug("File sync completed: %d files", stats.total_files)

            # Store sync info for display during cell execution
            sync_time_str = self._format_time(sync_elapsed)
            self._sync_info = f"Synced {stats.total_files} files in {sync_time_str}"

            return True, sync_elapsed, stats.total_files

        except Exception as e:
            logger.warning("File sync failed: %s", e)
            self.send_response(
                self.iopub_socket,
                "stream",
                {"name": "stderr", "text": f"✗ Sync failed: {e}\n"},
            )
            # Continue execution even if sync fails
            return True, 0.0, 0

    def _handle_reconnection(self) -> None:
        """Handle session reconnection.

        Re-runs the setup code to restore sys.path and notifies the user.
        """
        logger.info("Session reconnected, restoring sys.path")
        # Notify user about reconnection
        self.send_response(
            self.iopub_socket,
            "stream",
            {
                "name": "stderr",
                "text": "Session reconnected. Variables have been reset.\n",
            },
        )

        # Re-run setup code if we have synced files before
        if self.file_sync and self._last_dbfs_path and self.executor:
            try:
                setup_code = self.file_sync.get_setup_code(self._last_dbfs_path)
                result = self.executor.execute(setup_code, allow_reconnect=False)
                if result.status != "ok":
                    err = result.error
                    logger.warning("Failed to restore sys.path: %s", err)
                    self.send_response(
                        self.iopub_socket,
                        "stream",
                        {
                            "name": "stderr",
                            "text": f"Warning: Failed to restore sys.path: {err}\n",
                        },
                    )
            except Exception as e:
                # Notify user but don't fail the main execution
                logger.warning("Failed to restore sys.path: %s", e)
                self.send_response(
                    self.iopub_socket,
                    "stream",
                    {
                        "name": "stderr",
                        "text": f"Warning: Failed to restore sys.path: {e}\n",
                    },
                )

    def _send_progress(
        self,
        cluster_state: str,
        command_status: str,
        elapsed_seconds: float,
    ) -> None:
        """Send progress update to the frontend.

        Uses display_data with transient flag so output is not persisted.

        Args:
            cluster_state: Current cluster state (e.g., "RUNNING").
            command_status: Current command status (e.g., "RUNNING").
            elapsed_seconds: Elapsed time in seconds.
        """
        # Get spinner character
        spinner = SPINNER_CHARS[self._spinner_index % len(SPINNER_CHARS)]
        self._spinner_index += 1

        # Format elapsed time with 1 decimal for smooth animation feedback
        elapsed_str = f"{elapsed_seconds:.1f}s"

        # Build progress message lines
        lines = []

        # Add sync info if available (first line)
        if self._sync_info:
            lines.append(f"✓ {self._sync_info}")

        # Add execution progress (with spinner)
        lines.append(
            f"{spinner} Cluster: {cluster_state} | "
            f"Command: {command_status} | {elapsed_str}"
        )

        # Add driver logs URL
        if self._driver_logs_url:
            lines.append(f"  Driver logs: {self._driver_logs_url}")

        progress_text = "\n".join(lines)

        # Use display_id for in-place updates
        # First call creates the display, subsequent calls update it
        # Include execution_count to make ID unique per cell execution
        if not self._progress_display_id:
            self._progress_display_id = f"progress-{self.execution_count}"
            # First display - create it
            self.send_response(
                self.iopub_socket,
                "display_data",
                {
                    "data": {"text/plain": progress_text},
                    "metadata": {},
                    "transient": {"display_id": self._progress_display_id},
                },
            )
        else:
            # Update existing display
            self.send_response(
                self.iopub_socket,
                "update_display_data",
                {
                    "data": {"text/plain": progress_text},
                    "metadata": {},
                    "transient": {"display_id": self._progress_display_id},
                },
            )

    def _format_time(self, seconds: float) -> str:
        """Format time in seconds to human-readable string.

        Args:
            seconds: Time in seconds.

        Returns:
            Formatted time string (e.g., "1.2s" or "45s").
        """
        if seconds < 10:
            return f"{seconds:.1f}s"
        return f"{seconds:.0f}s"

    def _format_completion_text(
        self,
        exec_seconds: float,
    ) -> str:
        """Format completion message text.

        Args:
            exec_seconds: Cell execution time in seconds.

        Returns:
            Formatted completion message string (multiple lines if sync occurred).
        """
        lines = []

        # Add sync info if available
        if self._sync_info:
            lines.append(f"✓ {self._sync_info}")

        # Add execution time
        exec_str = self._format_time(exec_seconds)
        lines.append(f"✓ Cell executed in {exec_str}")

        # Add separator line to distinguish from output
        lines.append("─" * 40)

        return "\n".join(lines)

    async def do_execute(
        self,
        code: Any,
        silent: Any,
        store_history: Any = True,
        user_expressions: Any = None,
        allow_stdin: Any = False,
        *,
        cell_meta: Any = None,
        cell_id: Any = None,
    ) -> dict[str, Any]:
        """Execute code on the Databricks cluster.

        Args:
            code: The code to execute.
            silent: Whether to suppress output.
            store_history: Whether to store the code in history.
            user_expressions: User expressions to evaluate.
            allow_stdin: Whether to allow stdin.
            cell_id: The cell ID.

        Returns:
            Execution result dictionary.
        """
        # Skip empty code
        code_str = str(code).strip()
        if not code_str:
            return {
                "status": "ok",
                "execution_count": self.execution_count,
                "payload": [],
                "user_expressions": {},
            }

        # Initialize on first execution
        if not self._initialize():
            return {
                "status": "error",
                "execution_count": self.execution_count,
                "ename": "ConfigurationError",
                "evalue": "Failed to initialize Databricks connection",
                "traceback": [],
            }

        # Sync files before execution
        sync_success, sync_elapsed, sync_file_count = self._sync_files()
        if not sync_success:
            return {
                "status": "error",
                "execution_count": self.execution_count,
                "ename": "SyncError",
                "evalue": "File sync failed",
                "traceback": [],
            }

        # Execute on Databricks with progress tracking
        assert self.executor is not None
        exec_start_time = time.time()
        try:
            result = self.executor.execute(
                code_str,
                on_progress=self._send_progress if not silent else None,
            )
            exec_elapsed = time.time() - exec_start_time

            # Handle reconnection: re-run setup code and notify user
            if result.reconnected:
                logger.debug("Execution triggered reconnection")
                self._handle_reconnection()

            logger.debug("Execution completed: status=%s", result.status)

            if result.status == "ok":
                if not silent:
                    # Update progress display to show completion message
                    if self._progress_display_id:
                        completion_text = self._format_completion_text(exec_elapsed)
                        self.send_response(
                            self.iopub_socket,
                            "update_display_data",
                            {
                                "data": {"text/plain": completion_text},
                                "metadata": {},
                                "transient": {"display_id": self._progress_display_id},
                            },
                        )
                        self._progress_display_id = None
                        self._spinner_index = 0
                        self._sync_info = None  # Reset for next execution

                    # Display text output
                    if result.output:
                        self.send_response(
                            self.iopub_socket,
                            "stream",
                            {"name": "stdout", "text": result.output},
                        )

                    # Display images
                    if result.images:
                        for image_data in result.images:
                            mime_type, base64_data = self._parse_data_url(image_data)
                            if mime_type and base64_data:
                                self.send_response(
                                    self.iopub_socket,
                                    "display_data",
                                    {
                                        "data": {mime_type: base64_data},
                                        "metadata": {},
                                    },
                                )

                    # Display table
                    if result.table_data is not None:
                        html_table = self._generate_html_table(
                            result.table_data, result.table_schema
                        )
                        self.send_response(
                            self.iopub_socket,
                            "display_data",
                            {
                                "data": {"text/html": html_table},
                                "metadata": {},
                            },
                        )

                return {
                    "status": "ok",
                    "execution_count": self.execution_count,
                    "payload": [],
                    "user_expressions": {},
                }
            else:
                # Handle error
                error_msg = result.error or "Unknown error"
                traceback = result.traceback or []

                if not silent:
                    self.send_response(
                        self.iopub_socket,
                        "error",
                        {
                            "ename": "ExecutionError",
                            "evalue": error_msg,
                            "traceback": traceback,
                        },
                    )
                return {
                    "status": "error",
                    "execution_count": self.execution_count,
                    "ename": "ExecutionError",
                    "evalue": error_msg,
                    "traceback": traceback,
                }

        except Exception as e:
            logger.error("Execution error: %s", e)
            error_msg = str(e)
            if not silent:
                self.send_response(
                    self.iopub_socket,
                    "error",
                    {
                        "ename": type(e).__name__,
                        "evalue": error_msg,
                        "traceback": [error_msg],
                    },
                )
            return {
                "status": "error",
                "execution_count": self.execution_count,
                "ename": type(e).__name__,
                "evalue": error_msg,
                "traceback": [error_msg],
            }

    def _parse_data_url(self, data_url: str) -> tuple[str | None, str | None]:
        """Parse a Data URL into MIME type and base64 data.

        Args:
            data_url: Data URL string (e.g., "data:image/png;base64,iVBOR...").

        Returns:
            Tuple of (mime_type, base64_data) or (None, None) if invalid.
        """
        if not data_url.startswith("data:"):
            return None, None

        try:
            # data:image/png;base64,iVBOR...
            header, base64_data = data_url.split(",", 1)
            # data:image/png;base64
            mime_part = header[5:]  # Remove "data:"
            # image/png;base64 -> image/png
            mime_type = mime_part.split(";")[0]
            return mime_type, base64_data
        except (ValueError, IndexError):
            return None, None

    def _generate_html_table(
        self,
        data: list[list[Any]],
        schema: list[dict[str, Any]] | None,
    ) -> str:
        """Generate an HTML table from table data.

        Args:
            data: List of rows, where each row is a list of cell values.
            schema: Optional list of column definitions with "name" keys.

        Returns:
            HTML table string.
        """
        html_parts = ['<table border="1" class="dataframe">']

        # Header
        if schema:
            html_parts.append("<thead><tr>")
            for col in schema:
                name = col.get("name", "")
                html_parts.append(f"<th>{html.escape(str(name))}</th>")
            html_parts.append("</tr></thead>")

        # Body
        html_parts.append("<tbody>")
        for row in data:
            html_parts.append("<tr>")
            for cell in row:
                cell_str = "" if cell is None else str(cell)
                html_parts.append(f"<td>{html.escape(cell_str)}</td>")
            html_parts.append("</tr>")
        html_parts.append("</tbody>")

        html_parts.append("</table>")
        return "".join(html_parts)

    async def do_shutdown(self, restart: bool) -> dict[str, Any]:
        """Shutdown the kernel.

        Args:
            restart: Whether this is a restart.

        Returns:
            Shutdown result dictionary.
        """
        logger.info("Shutting down kernel: restart=%s", restart)
        if restart:
            # On restart, keep the execution context alive for session continuity
            # Only reset the initialized flag so we can re-initialize on next execute
            self._initialized = False
            return {"status": "ok", "restart": restart}

        # Full shutdown: clean up everything
        # Clean up file sync
        if self.file_sync:
            try:
                self.file_sync.cleanup()
            except Exception as e:
                logger.debug("File sync cleanup error (ignored): %s", e)
            self.file_sync = None

        # Destroy execution context
        if self.executor:
            try:
                self.executor.destroy_context()
            except Exception as e:
                logger.debug("Executor cleanup error (ignored): %s", e)
            self.executor = None

        self._initialized = False
        self._last_dbfs_path = None
        logger.debug("Kernel shutdown complete")
        return {"status": "ok", "restart": restart}
