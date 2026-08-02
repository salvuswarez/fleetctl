"""Tests for distribution version lookup."""

from __future__ import annotations

from importlib import metadata

import pytest

from fleetctl._version import _FALLBACK_VERSION, get_version


def test_returns_the_installed_distribution_version(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setattr(metadata, "version", lambda name: "1.2.3")

    # Act
    actual = get_version()

    # Assert
    assert actual == "1.2.3"


def test_falls_back_when_the_distribution_is_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    def _raise(name: str) -> str:
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(metadata, "version", _raise)

    # Act
    actual = get_version()

    # Assert
    assert actual == _FALLBACK_VERSION
