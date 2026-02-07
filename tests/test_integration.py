"""Integration tests for jupyter-databricks-kernel.

These tests require a real Databricks cluster and valid credentials.
They are skipped in CI environments where cluster_id is not configured.

Run with: pytest -m integration
Skip with: pytest -m "not integration"

To use a specific Databricks profile (e.g., Service Principal):
    DATABRICKS_CONFIG_PROFILE=oauth-m2m-test pytest -m integration

The DATABRICKS_CONFIG_PROFILE environment variable is automatically
respected by both Config.load() and WorkspaceClient().
"""

from __future__ import annotations

import os

import pytest

from jupyter_databricks_kernel.config import Config


def _has_cluster_id() -> bool:
    """Check if cluster_id is available from env or ~/.databrickscfg.

    Respects DATABRICKS_CONFIG_PROFILE environment variable to select
    a specific profile from ~/.databrickscfg (defaults to DEFAULT).
    """
    if os.environ.get("DATABRICKS_CLUSTER_ID"):
        return True
    try:
        config = Config.load()
        return bool(config.cluster_id)
    except Exception:
        return False


# Skip all tests in this module if no cluster is configured
SKIP_INTEGRATION = not _has_cluster_id()
SKIP_REASON = "cluster_id not configured (env or ~/.databrickscfg)"


@pytest.mark.integration
@pytest.mark.skipif(SKIP_INTEGRATION, reason=SKIP_REASON)
class TestRealClusterExecution:
    """Integration tests that run against a real Databricks cluster."""

    def test_create_and_destroy_context(self) -> None:
        """Test creating and destroying an execution context on a real cluster."""
        from jupyter_databricks_kernel.config import Config
        from jupyter_databricks_kernel.executor import DatabricksExecutor

        try:
            config = Config.load()
            executor = DatabricksExecutor(config)
            executor.create_context()
            assert executor.context_id is not None
            assert len(executor.context_id) > 0
        except Exception as e:
            auth_keywords = ["auth", "token", "credential", "permission"]
            if any(keyword in str(e).lower() for keyword in auth_keywords):
                pytest.skip(f"Databricks authentication not available: {e}")
            raise
        finally:
            if "executor" in locals():
                executor.destroy_context()
                assert executor.context_id is None

    def test_execute_simple_code(self) -> None:
        """Test executing simple Python code on a real cluster."""
        from jupyter_databricks_kernel.config import Config
        from jupyter_databricks_kernel.executor import DatabricksExecutor

        try:
            config = Config.load()
            executor = DatabricksExecutor(config)
            result = executor.execute("print('Hello from Databricks')")
            assert result.status == "ok"
        except Exception as e:
            auth_keywords = ["auth", "token", "credential", "permission"]
            if any(keyword in str(e).lower() for keyword in auth_keywords):
                pytest.skip(f"Databricks authentication not available: {e}")
            raise
        finally:
            if "executor" in locals():
                executor.destroy_context()

    def test_execute_with_output(self) -> None:
        """Test executing code that returns a value on a real cluster."""
        from jupyter_databricks_kernel.config import Config
        from jupyter_databricks_kernel.executor import DatabricksExecutor

        try:
            config = Config.load()
            executor = DatabricksExecutor(config)
            result = executor.execute("1 + 1")
            assert result.status == "ok"
            assert result.output is not None
        except Exception as e:
            auth_keywords = ["auth", "token", "credential", "permission"]
            if any(keyword in str(e).lower() for keyword in auth_keywords):
                pytest.skip(f"Databricks authentication not available: {e}")
            raise
        finally:
            if "executor" in locals():
                executor.destroy_context()

    def test_execute_with_error(self) -> None:
        """Test executing code that raises an error on a real cluster."""
        from jupyter_databricks_kernel.config import Config
        from jupyter_databricks_kernel.executor import DatabricksExecutor

        try:
            config = Config.load()
            executor = DatabricksExecutor(config)
            result = executor.execute("raise ValueError('test error')")
            assert result.status == "error"
            assert result.error is not None
            assert "ValueError" in result.error or "test error" in result.error
        except Exception as e:
            auth_keywords = ["auth", "token", "credential", "permission"]
            if any(keyword in str(e).lower() for keyword in auth_keywords):
                pytest.skip(f"Databricks authentication not available: {e}")
            raise
        finally:
            if "executor" in locals():
                executor.destroy_context()


@pytest.mark.integration
@pytest.mark.skipif(SKIP_INTEGRATION, reason=SKIP_REASON)
class TestRealClusterSync:
    """Integration tests for file sync with a real Databricks cluster."""

    def test_get_user_name(self) -> None:
        """Test getting the current user name from a real cluster."""
        from jupyter_databricks_kernel.config import Config
        from jupyter_databricks_kernel.sync import FileSync

        try:
            config = Config.load()
            file_sync = FileSync(config, "test-session")
            # Access the private method to test user name retrieval
            client = file_sync._ensure_client()
            user = client.current_user.me()

            assert user is not None
            assert user.user_name is not None
            assert len(user.user_name) > 0
        except Exception as e:
            auth_keywords = ["auth", "token", "credential", "permission"]
            if any(keyword in str(e).lower() for keyword in auth_keywords):
                pytest.skip(f"Databricks authentication not available: {e}")
            raise
