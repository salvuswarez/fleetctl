"""Tests for credential redaction."""

from __future__ import annotations

import pytest

from fleetctl.core.observability.redact import MASK, Redactor


@pytest.mark.parametrize(
    "raw",
    [
        "curl http://admin:hunter2@192.168.1.50/playlist.m3u",
        "m3uPath=http://iptv.example.com/get.php?username=bob&password=hunter2",
        "export FLEETCTL_SMB_PASS=hunter2",
        "token: ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        "github_pat_11ABCDEFG_shouldnotsurvive",
    ],
)
def test_credential_shapes_are_masked(raw: str) -> None:
    # Arrange
    redactor = Redactor()

    # Act
    actual = redactor.text(raw)

    # Assert
    assert "hunter2" not in actual
    assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in actual
    assert "github_pat_11ABCDEFG_shouldnotsurvive" not in actual
    assert MASK in actual


def test_identifying_context_survives_redaction() -> None:
    """A redacted record must still say what was removed, or it is useless
    for running an incident down."""
    # Arrange
    redactor = Redactor()

    # Act
    actual = redactor.text("curl http://admin:hunter2@192.168.1.50/playlist.m3u")

    # Assert
    assert "admin" in actual
    assert "192.168.1.50" in actual
    assert "hunter2" not in actual


def test_secret_reference_pointers_are_left_intact() -> None:
    """`!ref` pointers are not secrets — masking them would make config
    diagnostics useless."""
    # Arrange
    redactor = Redactor()

    # Act
    actual = redactor.text("password: !ref env:FLEETCTL_SMB_PASS")

    # Assert
    assert actual == "password: !ref env:FLEETCTL_SMB_PASS"


def test_sensitive_mapping_keys_are_masked_wholesale() -> None:
    # Arrange
    redactor = Redactor()
    record = {"host": "192.168.1.50", "password": "hunter2", "nested": {"api_key": "abc123"}}

    # Act
    actual = redactor.mapping(record)

    # Assert
    assert actual == {"host": "192.168.1.50", "password": MASK, "nested": {"api_key": MASK}}


def test_mapping_redaction_does_not_mutate_the_input() -> None:
    # Arrange
    redactor = Redactor()
    record = {"password": "hunter2"}

    # Act
    redactor.mapping(record)

    # Assert
    assert record == {"password": "hunter2"}


def test_credentials_hiding_in_innocuously_named_fields_are_still_caught() -> None:
    # Arrange
    redactor = Redactor()
    record = {"command": "curl http://admin:hunter2@192.168.1.50/"}

    # Act
    actual = redactor.mapping(record)

    # Assert
    assert "hunter2" not in actual["command"]
