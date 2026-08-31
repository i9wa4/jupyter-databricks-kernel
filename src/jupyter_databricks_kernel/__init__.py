"""Jupyter kernel for Databricks remote execution."""

import sys
import warnings
from collections.abc import Sequence

from ._version import __version__


def _warn_if_python_311(version_info: Sequence[int] | None = None) -> None:
    """Warn when the current interpreter is Python 3.11."""
    version = sys.version_info if version_info is None else version_info
    if tuple(version[:2]) != (3, 11):
        return

    warnings.warn(
        "Python 3.11 support is deprecated and will be removed in v2.0; "
        "upgrade to Python 3.12 or later.",
        DeprecationWarning,
        stacklevel=2,
    )


_warn_if_python_311()

__all__ = ["__version__"]
