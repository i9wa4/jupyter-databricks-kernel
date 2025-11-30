"""Databricks execution context management."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from databricks.sdk import WorkspaceClient
from databricks.sdk.service import compute

if TYPE_CHECKING:
    from .config import Config


@dataclass
class ExecutionResult:
    """Result of a command execution."""

    status: str
    output: str | None = None
    error: str | None = None
    traceback: list[str] | None = None


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

    def create_context(self) -> None:
        """Create an execution context on the Databricks cluster."""
        if self.context_id is not None:
            return  # Context already exists

        if not self.config.cluster_id:
            raise ValueError("Cluster ID is not configured")

        client = self._ensure_client()
        response = client.command_execution.create(
            cluster_id=self.config.cluster_id,
            language=compute.Language.PYTHON,
        ).result()

        if response and response.id:
            self.context_id = response.id

    def execute(self, code: str) -> ExecutionResult:
        """Execute code on the Databricks cluster.

        Args:
            code: The Python code to execute.

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

        client = self._ensure_client()
        response = client.command_execution.execute(
            cluster_id=self.config.cluster_id,
            context_id=self.context_id,
            language=compute.Language.PYTHON,
            command=code,
        ).result()

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
