"""Tests for the CLI entry point."""

from __future__ import annotations

import logging

import click
import pytest
from click.testing import CliRunner

from fleetctl._version import get_version
from fleetctl.cli.main import configure_logging, main


def test_version_flag_reports_the_installed_version() -> None:
    # Arrange
    runner = CliRunner()

    # Act
    result = runner.invoke(main, ["--version"])

    # Assert
    assert result.exit_code == 0
    assert get_version() in result.output


def test_help_lists_the_group_description() -> None:
    # Arrange
    runner = CliRunner()

    # Act
    result = runner.invoke(main, ["--help"])

    # Assert
    assert result.exit_code == 0
    assert "Manage a fleet of home devices." in result.output


def test_group_callback_configures_logging_from_the_verbose_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """The callback only runs when a subcommand is invoked, and `--help` is
    eager enough to short-circuit it — so exercise it through a throwaway
    subcommand on a clone of the real group rather than mutating `main`."""
    # Arrange
    seen: list[int] = []
    monkeypatch.setattr("fleetctl.cli.main.configure_logging", seen.append)
    group = click.Group("fleetctl", params=main.params, callback=main.callback)

    @group.command("noop")
    def _noop() -> None: ...

    # Act
    result = CliRunner().invoke(group, ["-vv", "noop"])

    # Assert
    assert result.exit_code == 0
    assert seen == [2]


@pytest.mark.parametrize(
    ("verbose", "expected"),
    [(0, logging.WARNING), (1, logging.INFO), (2, logging.DEBUG), (3, logging.DEBUG)],
)
def test_configure_logging_maps_verbosity_to_level(verbose: int, expected: int) -> None:
    # Arrange
    root = logging.getLogger()
    original_level = root.level
    original_handlers = list(root.handlers)
    root.handlers.clear()

    # Act
    try:
        configure_logging(verbose)
        actual = root.level
    finally:
        root.handlers.clear()
        root.handlers.extend(original_handlers)
        root.setLevel(original_level)

    # Assert
    assert actual == expected
