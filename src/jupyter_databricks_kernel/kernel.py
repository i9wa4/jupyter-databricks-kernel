"""Databricks Session Kernel for Jupyter."""

from __future__ import annotations

import uuid
from typing import Any

from ipykernel.kernelbase import Kernel

from . import __version__
from .config import Config
from .executor import DatabricksExecutor
from .sync import FileSync


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

    def _initialize(self) -> bool:
        """Initialize the Databricks connection.

        Returns:
            True if initialization succeeded, False otherwise.
        """
        if self._initialized:
            return True

        # Validate configuration
        errors = self._kernel_config.validate()
        if errors:
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
        if self.file_sync is None:
            self.file_sync = FileSync(self._kernel_config, self._session_id)
        self._initialized = True
        return True

    def _sync_files(self) -> bool:
        """Synchronize files if needed.

        Returns:
            True if sync succeeded or was not needed, False on error.
        """
        if self.file_sync is None or self.executor is None:
            return True

        if not self.file_sync.needs_sync():
            return True

        try:
            self.send_response(
                self.iopub_socket,
                "stream",
                {"name": "stderr", "text": "Syncing files to Databricks...\n"},
            )

            # Upload files
            dbfs_path = self.file_sync.sync()
            self._last_dbfs_path = dbfs_path

            # Execute setup code on remote
            setup_code = self.file_sync.get_setup_code(dbfs_path)
            result = self.executor.execute(setup_code, allow_reconnect=False)

            if result.status != "ok":
                self.send_response(
                    self.iopub_socket,
                    "stream",
                    {"name": "stderr", "text": f"Sync setup failed: {result.error}\n"},
                )
                return False

            self.send_response(
                self.iopub_socket,
                "stream",
                {"name": "stderr", "text": "Files synced successfully.\n"},
            )
            return True

        except Exception as e:
            self.send_response(
                self.iopub_socket,
                "stream",
                {"name": "stderr", "text": f"Sync failed: {e}\n"},
            )
            # Continue execution even if sync fails
            return True

    def _handle_reconnection(self) -> None:
        """Handle session reconnection.

        Re-runs the setup code to restore sys.path and notifies the user.
        """
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
                self.send_response(
                    self.iopub_socket,
                    "stream",
                    {
                        "name": "stderr",
                        "text": f"Warning: Failed to restore sys.path: {e}\n",
                    },
                )

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
        self._sync_files()

        # Execute on Databricks
        assert self.executor is not None
        try:
            result = self.executor.execute(code_str)

            # Handle reconnection: re-run setup code and notify user
            if result.reconnected:
                self._handle_reconnection()

            if result.status == "ok":
                if not silent and result.output:
                    self.send_response(
                        self.iopub_socket,
                        "stream",
                        {"name": "stdout", "text": result.output},
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

    async def do_shutdown(self, restart: bool) -> dict[str, Any]:
        """Shutdown the kernel.

        Args:
            restart: Whether this is a restart.

        Returns:
            Shutdown result dictionary.
        """
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
            except Exception:
                pass
            self.file_sync = None

        # Destroy execution context
        if self.executor:
            try:
                self.executor.destroy_context()
            except Exception:
                pass
            self.executor = None

        self._initialized = False
        self._last_dbfs_path = None
        return {"status": "ok", "restart": restart}
