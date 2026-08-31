"""Tests for package startup behavior."""

from __future__ import annotations

import importlib
import sys
import warnings

import pytest

import jupyter_databricks_kernel
from jupyter_databricks_kernel import _warn_if_python_311


def _reload_package_with_version(
    monkeypatch: pytest.MonkeyPatch, version_info: tuple[int, int, int]
) -> list[warnings.WarningMessage]:
    """Reload the package with a simulated interpreter version."""
    monkeypatch.setattr(sys, "version_info", version_info)
    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter("always")
        importlib.reload(jupyter_databricks_kernel)
    return caught_warnings


def test_warn_if_python_311_emits_deprecation_warning() -> None:
    """Python 3.11 receives a migration warning."""
    with pytest.warns(
        DeprecationWarning,
        match="Python 3.11 support is deprecated.*Python 3.12 or later",
    ):
        _warn_if_python_311((3, 11, 0))


def test_warn_if_python_311_ignores_newer_versions() -> None:
    """Python 3.12 and later do not receive the migration warning."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _warn_if_python_311((3, 12, 0))


def test_package_startup_warns_on_python_311(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Package startup emits exactly one migration warning on Python 3.11."""
    caught_warnings = _reload_package_with_version(monkeypatch, (3, 11, 0))

    warning_details = [
        (warning.category, str(warning.message)) for warning in caught_warnings
    ]
    assert warning_details == [
        (
            DeprecationWarning,
            "Python 3.11 support is deprecated and will be removed in v2.0; "
            "upgrade to Python 3.12 or later.",
        )
    ]


def test_package_startup_does_not_warn_on_python_312_or_later(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Package startup does not emit the migration warning on Python 3.12+."""
    caught_warnings = _reload_package_with_version(monkeypatch, (3, 12, 0))

    assert caught_warnings == []
