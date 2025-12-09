"""Shared pytest fixtures for jupyter-databricks-kernel tests."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, Mock

import pytest

if TYPE_CHECKING:
    from jupyter_databricks_kernel.executor import DatabricksExecutor
    from jupyter_databricks_kernel.sync import FileSync


@pytest.fixture
def mock_workspace_client() -> MagicMock:
    """Create a mock WorkspaceClient for dependency injection.

    This fixture provides a fully configured mock of the Databricks SDK
    WorkspaceClient with common API responses pre-configured.

    Returns:
        A MagicMock configured to behave like WorkspaceClient.
    """
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service import compute

    client: MagicMock = MagicMock(spec=WorkspaceClient)

    # command_execution API
    context_response = Mock()
    context_response.id = "test-context-id"
    client.command_execution.create.return_value.result.return_value = context_response

    execute_response = Mock()
    execute_response.status = compute.CommandStatus.FINISHED
    execute_response.results = Mock(data="output", cause=None, summary=None)
    client.command_execution.execute.return_value.result.return_value = execute_response

    # clusters API
    cluster_info = Mock()
    cluster_info.state = compute.State.RUNNING
    client.clusters.get.return_value = cluster_info

    # current_user API
    user_info = Mock()
    user_info.user_name = "test@example.com"
    client.current_user.me.return_value = user_info

    # dbfs API - context manager for file operations
    dbfs_file = MagicMock()
    client.dbfs.open.return_value.__enter__ = Mock(return_value=dbfs_file)
    client.dbfs.open.return_value.__exit__ = Mock(return_value=False)

    return client


@pytest.fixture
def mock_config() -> MagicMock:
    """Create a mock Config for testing.

    Returns:
        A MagicMock configured to behave like Config.
    """
    config: MagicMock = MagicMock()
    config.cluster_id = "test-cluster-id"
    config.validate.return_value = []

    # SyncConfig mock
    config.sync = MagicMock()
    config.sync.enabled = True
    config.sync.source = "."
    config.sync.exclude = []
    config.sync.max_size_mb = None
    config.sync.max_file_size_mb = None
    config.sync.use_gitignore = True

    return config


@pytest.fixture
def mock_executor(
    mock_config: MagicMock,
    mock_workspace_client: MagicMock,
) -> DatabricksExecutor:
    """Create a DatabricksExecutor with injected mock dependencies.

    Args:
        mock_config: Mock configuration.
        mock_workspace_client: Mock WorkspaceClient.

    Returns:
        DatabricksExecutor instance with mocked dependencies.
    """
    from jupyter_databricks_kernel.executor import DatabricksExecutor

    return DatabricksExecutor(mock_config, client=mock_workspace_client)


@pytest.fixture
def mock_file_sync(
    mock_config: MagicMock,
    mock_workspace_client: MagicMock,
) -> FileSync:
    """Create a FileSync with injected mock dependencies.

    Args:
        mock_config: Mock configuration.
        mock_workspace_client: Mock WorkspaceClient.

    Returns:
        FileSync instance with mocked dependencies.
    """
    from jupyter_databricks_kernel.sync import FileSync

    return FileSync(mock_config, "test-session-id", client=mock_workspace_client)


# =============================================================================
# Scenario-specific fixtures
# =============================================================================


@pytest.fixture
def mock_client_context_error(mock_workspace_client: MagicMock) -> MagicMock:
    """Create a mock client that raises context errors.

    Use this fixture to test reconnection logic.

    Args:
        mock_workspace_client: Base mock client.

    Returns:
        Mock client configured to raise context errors.
    """
    mock_workspace_client.command_execution.execute.return_value.result.side_effect = (
        Exception("Context not found")
    )
    return mock_workspace_client


@pytest.fixture
def mock_client_cluster_terminated(mock_workspace_client: MagicMock) -> MagicMock:
    """Create a mock client with a terminated cluster.

    Use this fixture to test cluster auto-start logic.

    Args:
        mock_workspace_client: Base mock client.

    Returns:
        Mock client configured with terminated cluster state.
    """
    from databricks.sdk.service import compute

    cluster_info = Mock()
    cluster_info.state = compute.State.TERMINATED
    mock_workspace_client.clusters.get.return_value = cluster_info
    return mock_workspace_client


@pytest.fixture
def mock_client_timeout(mock_workspace_client: MagicMock) -> MagicMock:
    """Create a mock client that raises timeout errors.

    Use this fixture to test timeout handling.

    Args:
        mock_workspace_client: Base mock client.

    Returns:
        Mock client configured to raise timeout errors.
    """
    from concurrent.futures import TimeoutError

    mock_workspace_client.command_execution.execute.return_value.result.side_effect = (
        TimeoutError("Command execution timed out")
    )
    return mock_workspace_client
