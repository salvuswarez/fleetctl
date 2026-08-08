"""Tests for secret references and layered config resolution."""

from __future__ import annotations

import pytest

from fleetctl.core.config.layering import Layer, for_device, resolve
from fleetctl.core.config.secrets import (
    EnvSecretProvider,
    MappingSecretProvider,
    Secret,
    SecretRef,
    SecretResolver,
)
from fleetctl.core.errors import SecretResolutionError
from fleetctl.core.observability.redact import Redactor


@pytest.mark.parametrize(
    ("raw", "scheme", "locator"),
    [
        ("!ref env:FLEETCTL_SMB_PASS", "env", "FLEETCTL_SMB_PASS"),
        ("!ref keyring:fleetctl/workshop", "keyring", "fleetctl/workshop"),
        ("  !ref  env:X  ", "env", "X"),
    ],
)
def test_references_are_parsed(raw: str, scheme: str, locator: str) -> None:
    # Act
    ref = SecretRef.parse(raw)

    # Assert
    assert ref is not None
    assert (ref.scheme, ref.locator) == (scheme, locator)


@pytest.mark.parametrize("raw", ["hunter2", "ref env:X", "!ref nocolon", ""])
def test_ordinary_strings_are_not_references(raw: str) -> None:
    assert SecretRef.parse(raw) is None


def test_a_secret_does_not_render_itself() -> None:
    """The predecessor's config dataclass would have printed its password
    from the generated repr."""
    # Arrange
    secret = Secret("hunter2", origin="env:FLEETCTL_SMB_PASS")

    # Act / Assert
    assert str(secret) == "**********"
    assert "hunter2" not in repr(secret)
    assert "hunter2" not in f"{secret}"
    assert secret.reveal() == "hunter2"


def test_a_secret_survives_redaction_as_a_mask() -> None:
    # Arrange
    redactor = Redactor()

    # Act
    actual = redactor.mapping({"smb": {"password": Secret("hunter2")}})

    # Assert
    assert "hunter2" not in str(actual)


def test_env_provider_resolves_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("FLEETCTL_TEST_SECRET", "hunter2")
    resolver = SecretResolver(EnvSecretProvider())

    # Act
    secret = resolver.resolve(SecretRef("env", "FLEETCTL_TEST_SECRET"))

    # Assert
    assert secret.reveal() == "hunter2"


def test_an_unset_variable_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    """A silently empty credential surfaces later as an unexplained auth
    failure, which is far harder to diagnose."""
    # Arrange
    monkeypatch.delenv("FLEETCTL_ABSENT", raising=False)
    resolver = SecretResolver(EnvSecretProvider())

    # Act / Assert
    with pytest.raises(SecretResolutionError):
        resolver.resolve(SecretRef("env", "FLEETCTL_ABSENT"))


def test_an_unknown_scheme_fails_loudly() -> None:
    # Arrange
    resolver = SecretResolver(EnvSecretProvider())

    # Act / Assert
    with pytest.raises(SecretResolutionError):
        resolver.resolve(SecretRef("vault", "anything"))


def test_the_error_names_the_reference_but_never_a_value() -> None:
    # Arrange
    resolver = SecretResolver(EnvSecretProvider())

    # Act
    with pytest.raises(SecretResolutionError) as caught:
        resolver.resolve(SecretRef("vault", "secret/path"))

    # Assert
    assert "vault:secret/path" in str(caught.value)


def test_resolve_all_walks_a_nested_config(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("FLEETCTL_TEST_SECRET", "hunter2")
    resolver = SecretResolver(EnvSecretProvider(), MappingSecretProvider({"kodi/db": "dbpass"}))
    config = {
        "artifacts": {"smb": {"host": "192.168.1.50", "password": "!ref env:FLEETCTL_TEST_SECRET"}},
        "apps": [{"db": "!ref entry:kodi/db"}],
    }

    # Act
    actual = resolver.resolve_all(config)

    # Assert
    assert actual["artifacts"]["smb"]["host"] == "192.168.1.50"
    assert actual["artifacts"]["smb"]["password"].reveal() == "hunter2"
    assert actual["apps"][0]["db"].reveal() == "dbpass"


def test_resolve_all_does_not_mutate_the_input(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("FLEETCTL_TEST_SECRET", "hunter2")
    config = {"password": "!ref env:FLEETCTL_TEST_SECRET"}

    # Act
    SecretResolver(EnvSecretProvider()).resolve_all(config)

    # Assert
    assert config == {"password": "!ref env:FLEETCTL_TEST_SECRET"}


def test_later_layers_win() -> None:
    # Act
    actual = resolve([Layer("pack", {"timeout": 30}), Layer("device", {"timeout": 90})])

    # Assert
    assert actual.get("timeout") == 90
    assert actual.origin("timeout") == "device"


def test_mappings_merge_recursively() -> None:
    # Act
    actual = resolve([Layer("pack", {"archive": {"gzip": True, "level": 6}}), Layer("device", {"archive": {"level": 9}})])

    # Assert
    assert actual.get("archive.gzip") is True
    assert actual.get("archive.level") == 9


def test_lists_replace_rather_than_concatenate() -> None:
    """An allow-list that silently grew by inheritance would be a security
    surprise, not a convenience."""
    # Act
    actual = resolve([Layer("pack", {"allow": ["a", "b"]}), Layer("device", {"allow": ["c"]})])

    # Assert
    assert actual.get("allow") == ["c"]


def test_the_full_precedence_order_holds() -> None:
    # Act
    actual = for_device(
        pack={"v": "pack"},
        fleet={"v": "fleet"},
        groups=[{"v": "group"}],
        device={"v": "device"},
        step={"v": "step"},
        flags={"v": "flags"},
    )

    # Assert
    assert actual.get("v") == "flags"
    assert actual.origin("v") == "flags"


def test_a_lower_layer_still_supplies_keys_no_one_else_sets() -> None:
    # Act
    actual = for_device(pack={"a": 1, "b": 2}, device={"b": 3})

    # Assert
    assert (actual.get("a"), actual.origin("a")) == (1, "pack")
    assert (actual.get("b"), actual.origin("b")) == (3, "device")


def test_explain_reports_provenance_for_every_key() -> None:
    """ "Why did this stick get that setting?" must be answerable without
    reading Python."""
    # Act
    lines = for_device(pack={"archive": {"gzip": True}}, device={"timeout": 90}).explain()

    # Assert
    assert "archive.gzip = True  [pack]" in lines
    assert "timeout = 90  [device]" in lines


def test_explain_masks_secrets() -> None:
    # Act
    lines = for_device(fleet={"password": Secret("hunter2")}).explain()

    # Assert
    assert lines == ["password = **********  [fleet]"]


def test_a_missing_path_returns_the_default() -> None:
    # Arrange
    resolved = for_device(pack={"a": {"b": 1}})

    # Act / Assert
    assert resolved.get("a.b") == 1
    assert resolved.get("a.z", "fallback") == "fallback"
    assert resolved.get("nope.deep", None) is None
