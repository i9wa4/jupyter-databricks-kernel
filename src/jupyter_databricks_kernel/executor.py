"""Databricks execution context management."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import TYPE_CHECKING

from databricks.sdk import WorkspaceClient
from databricks.sdk.service import compute

if TYPE_CHECKING:
    from .config import Config

logger = logging.getLogger(__name__)

# Retry and timeout configuration
RECONNECT_DELAY_SECONDS = 1.0  # Delay before reconnection attempt
CONTEXT_CREATION_TIMEOUT = timedelta(minutes=5)  # Timeout for context creation
COMMAND_EXECUTION_TIMEOUT = timedelta(minutes=10)  # Timeout for command execution
POLL_INTERVAL_SECONDS = 1.0  # Interval between status polls

# Type alias for progress callback
ProgressCallback = Callable[[str], None]

# Rotating dots pattern for progress indicator
PROGRESS_DOTS = [".", "..", "..."]

# Pre-compiled pattern for context error detection
# Matches errors that specifically relate to execution context invalidation
CONTEXT_ERROR_PATTERN = re.compile(
    r"context\s*(not\s*found|does\s*not\s*exist|is\s*invalid|expired)|"
    r"invalid\s*context|"
    r"\bcontext_id\b|"
    r"execution\s*context",
    re.IGNORECASE,
)


@dataclass
class ExecutionResult:
    """Result of a command execution."""

    status: str
    output: str | None = None
    error: str | None = None
    traceback: list[str] | None = None
    reconnected: bool = False


class DatabricksExecutor:
    """Manages Databricks execution context and command execution."""

    def __init__(self, config: Config) -> None:
        """Initialize the executor.

        Args:
            config: Kernel configuration.
        """
        self.config = config
        self.client: WorkspaceClient | None = None
        self.context_id: str | None = None

    def _ensure_client(self) -> WorkspaceClient:
        """Ensure the WorkspaceClient is initialized.

        Returns:
            The WorkspaceClient instance.
        """
        if self.client is None:
            self.client = WorkspaceClient()
        return self.client

    def _ensure_cluster_running(self) -> None:
        """Ensure the cluster is running, starting it if necessary.

        If the cluster is in TERMINATED state, this method will start it
        and wait until it reaches RUNNING state.
        """
        if not self.config.cluster_id:
            return

        client = self._ensure_client()
        cluster = client.clusters.get(self.config.cluster_id)

        if cluster.state == compute.State.TERMINATED:
            logger.info("Cluster is terminated, starting...")
            client.clusters.start(self.config.cluster_id)
            client.clusters.wait_get_cluster_running(self.config.cluster_id)
            logger.info("Cluster is now running")

    def create_context(self) -> None:
        """Create an execution context on the Databricks cluster."""
        self._ensure_cluster_running()

        if self.context_id is not None:
            return  # Context already exists

        if not self.config.cluster_id:
            raise ValueError("Cluster ID is not configured")

        client = self._ensure_client()
        response = client.command_execution.create(
            cluster_id=self.config.cluster_id,
            language=compute.Language.PYTHON,
        ).result(timeout=CONTEXT_CREATION_TIMEOUT)

        if response and response.id:
            self.context_id = response.id

    def reconnect(self) -> None:
        """Recreate the execution context.

        Destroys the old context (if any) and creates a new one.
        Used when the existing context becomes invalid.
        """
        logger.info("Reconnecting: creating new execution context")
        # Try to destroy old context to avoid resource leak on cluster
        # Ignore errors since context may already be invalid
        try:
            self.destroy_context()
        except Exception as e:
            logger.debug("Failed to destroy old context: %s", e)
            self.context_id = None
        self.create_context()

    def _is_context_invalid_error(self, error: Exception) -> bool:
        """Check if an error indicates the context is invalid.

        Only matches errors that specifically relate to execution context,
        not general errors like "File not found" or "Variable not found".

        Args:
            error: The exception to check.

        Returns:
            True if the error indicates context invalidation.
        """
        error_str = str(error)

        # Must contain "context" to be considered a context error (case-insensitive)
        if "context" not in error_str.lower():
            return False

        # Use pre-compiled pattern for efficient matching
        return CONTEXT_ERROR_PATTERN.search(error_str) is not None

    def execute(
        self,
        code: str,
        *,
        allow_reconnect: bool = True,
        on_progress: ProgressCallback | None = None,
    ) -> ExecutionResult:
        """Execute code on the Databricks cluster.

        Args:
            code: The Python code to execute.
            allow_reconnect: If True, attempt to reconnect on context errors.
            on_progress: Optional callback for progress updates during execution.

        Returns:
            Execution result containing output or error.
        """
        if self.context_id is None:
            self.create_context()

        if self.context_id is None:
            return ExecutionResult(
                status="error",
                error="Failed to create execution context",
            )

        if not self.config.cluster_id:
            return ExecutionResult(
                status="error",
                error="Cluster ID is not configured",
            )

        try:
            result = self._execute_with_polling(code, on_progress)
            return result
        except Exception as e:
            if allow_reconnect and self._is_context_invalid_error(e):
                logger.warning("Context invalid, attempting reconnection: %s", e)
                try:
                    # Wait before reconnection to avoid hammering the API
                    time.sleep(RECONNECT_DELAY_SECONDS)
                    self.reconnect()
                    result = self._execute_with_polling(code, on_progress)
                    return replace(result, reconnected=True)
                except Exception as retry_error:
                    logger.error("Reconnection failed: %s", retry_error)
                    return ExecutionResult(
                        status="error",
                        error=f"Reconnection failed: {retry_error}",
                    )
            else:
                logger.error("Execution failed: %s", e)
                return ExecutionResult(
                    status="error",
                    error=str(e),
                )

    def _execute_internal(self, code: str) -> ExecutionResult:
        """Internal execution without reconnection logic.

        Args:
            code: The Python code to execute.

        Returns:
            Execution result containing output or error.

        Raises:
            Exception: If execution fails due to API errors.
        """
        client = self._ensure_client()
        response = client.command_execution.execute(
            cluster_id=self.config.cluster_id,
            context_id=self.context_id,
            language=compute.Language.PYTHON,
            command=code,
        ).result(timeout=COMMAND_EXECUTION_TIMEOUT)

        if response is None:
            return ExecutionResult(
                status="error",
                error="No response from Databricks",
            )

        # Parse the response
        status = str(response.status) if response.status else "unknown"

        # Handle results
        if response.results:
            results = response.results

            # Check for error
            if results.cause:
                return ExecutionResult(
                    status="error",
                    error=results.cause,
                    traceback=results.summary.split("\n") if results.summary else None,
                )

            # Get output
            output = None
            if results.data is not None:
                output = str(results.data)
            elif results.summary:
                output = results.summary

            return ExecutionResult(
                status="ok",
                output=output,
            )

        return ExecutionResult(status=status)

    def _execute_with_polling(
        self,
        code: str,
        on_progress: ProgressCallback | None = None,
    ) -> ExecutionResult:
        """Execute code with polling for status updates.

        Args:
            code: The Python code to execute.
            on_progress: Optional callback for progress updates.

        Returns:
            Execution result containing output or error.

        Raises:
            Exception: If execution fails due to API errors.
        """
        client = self._ensure_client()

        # Start command execution (don't call result() yet)
        waiter = client.command_execution.execute(
            cluster_id=self.config.cluster_id,
            context_id=self.context_id,
            language=compute.Language.PYTHON,
            command=code,
        )

        # Get command_id from the Wait object
        command_id = waiter.command_id

        # Polling loop
        dot_index = 0
        start_time = time.monotonic()
        timeout_seconds = COMMAND_EXECUTION_TIMEOUT.total_seconds()

        while True:
            # Check timeout
            elapsed = time.monotonic() - start_time
            if elapsed >= timeout_seconds:
                raise TimeoutError(
                    f"Command execution timed out after {timeout_seconds} seconds"
                )

            # Get current status
            # cluster_id and context_id are guaranteed to be non-None at this point
            assert self.config.cluster_id is not None
            assert self.context_id is not None
            response = client.command_execution.command_status(
                cluster_id=self.config.cluster_id,
                context_id=self.context_id,
                command_id=command_id,
            )

            # Check if finished
            if response.status in (
                compute.CommandStatus.FINISHED,
                compute.CommandStatus.ERROR,
                compute.CommandStatus.CANCELLED,
            ):
                return self._parse_command_response(response)

            # Send progress update
            if on_progress:
                on_progress(f"Running{PROGRESS_DOTS[dot_index % len(PROGRESS_DOTS)]}")
                dot_index += 1

            # Wait before next poll
            time.sleep(POLL_INTERVAL_SECONDS)

    def _parse_command_response(
        self,
        response: compute.CommandStatusResponse,
    ) -> ExecutionResult:
        """Parse a CommandStatusResponse into an ExecutionResult.

        Args:
            response: The response from command_status.

        Returns:
            Parsed execution result.
        """
        if response is None:
            return ExecutionResult(
                status="error",
                error="No response from Databricks",
            )

        status = str(response.status) if response.status else "unknown"

        if response.results:
            results = response.results

            # Check for error
            if results.cause:
                return ExecutionResult(
                    status="error",
                    error=results.cause,
                    traceback=results.summary.split("\n") if results.summary else None,
                )

            # Get output
            output = None
            if results.data is not None:
                output = str(results.data)
            elif results.summary:
                output = results.summary

            return ExecutionResult(
                status="ok",
                output=output,
            )

        return ExecutionResult(status=status)

    def destroy_context(self) -> None:
        """Destroy the execution context."""
        if self.context_id is None:
            return

        if not self.config.cluster_id:
            return

        try:
            client = self._ensure_client()
            client.command_execution.destroy(
                cluster_id=self.config.cluster_id,
                context_id=self.context_id,
            )
        finally:
            self.context_id = None
