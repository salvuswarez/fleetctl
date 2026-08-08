"""The POSIX base's read path, against canned command output."""

from __future__ import annotations

import pytest

from fleetctl.core.effects import Effect
from fleetctl.core.transport.fake import FakeTransport
from fleetctl.packs.posix import actions

OS_RELEASE = "\n".join(
    [
        'NAME="Debian GNU/Linux"',
        "ID=debian",
        'VERSION_ID="12"',
        "# a comment the parser must skip",
        "",
        'PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"',
    ]
)

HOST_RESPONSES = {
    "cat /etc/os-release": OS_RELEASE,
    "uname -n": "workshop",
    "uname -r": "6.1.0-18-amd64",
    "uname -m": "x86_64",
}

# SteamOS 3.8 ships no `hostname` binary. Verified on hardware 2026-08-06:
# the command exits 127, which is why facts are read with `uname -n`.
STEAMOS_RESPONSES = {
    "cat /etc/os-release": 'NAME="SteamOS"\nID=steamos\nVERSION_ID="3.8.24"\nVARIANT_ID=steamdeck',
    "uname -n": "steamdeck",
    "uname -r": "6.16.12-valve24.5-1-neptune",
    "uname -m": "x86_64",
}


def test_read_facts_reports_what_the_host_answered() -> None:
    # Arrange
    transport = FakeTransport(responses=HOST_RESPONSES)

    # Act
    facts = actions.read_facts(transport)

    # Assert
    assert facts == {
        "model": "debian",
        "manufacturer": "Debian GNU/Linux",
        "os_version": "12",
        "name": "workshop",
        "kernel": "6.1.0-18-amd64",
        "arch": "x86_64",
    }


def test_read_facts_omits_keys_the_host_did_not_answer() -> None:
    """A missing key means no answer, which is different from an empty one."""
    # Arrange
    transport = FakeTransport(responses={"cat /etc/os-release": "ID=arch", "uname -n": ""})

    # Act
    facts = actions.read_facts(transport)

    # Assert
    assert facts == {"model": "arch"}


def test_a_host_name_is_read_without_the_hostname_binary() -> None:
    """SteamOS ships no `hostname`; it exits 127 and the name was silently
    lost. Verified against a Steam Deck on 2026-08-06."""
    # Arrange
    transport = FakeTransport(responses=STEAMOS_RESPONSES)

    # Act
    facts = actions.read_facts(transport)

    # Assert
    assert facts["name"] == "steamdeck"
    assert "hostname" not in transport.commands()


def test_reading_facts_never_declares_a_mutating_effect() -> None:
    """A probe sweeps hosts that are not ours. Every command it sends must be
    classified READ or the policy layer cannot tell a scan from a change."""
    # Arrange
    transport = FakeTransport(responses=HOST_RESPONSES)

    # Act
    actions.read_facts(transport)

    # Assert
    assert {call.effect for call in transport.calls} == {Effect.READ}


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ('NAME="Debian GNU/Linux"', {"NAME": "Debian GNU/Linux"}),
        ("ID=steamos", {"ID": "steamos"}),
        ("ID='arch'", {"ID": "arch"}),
        ("# comment", {}),
        ("", {}),
        ("malformed line without an equals", {}),
    ],
)
def test_os_release_parsing_survives_whatever_a_host_answers(line: str, expected: dict[str, str]) -> None:
    # Act / Assert
    assert actions.parse_os_release(line) == expected


def test_health_adds_uptime_and_free_space() -> None:
    # Arrange
    transport = FakeTransport(
        responses={
            **HOST_RESPONSES,
            "cat /proc/uptime": "7200.42 14400.00",
            "df -k /": "Filesystem 1K-blocks Used Available Use% Mounted on\n/dev/sda1 100000000 40000000 2097152 40% /",
        }
    )

    # Act
    facts = actions.health(transport)

    # Assert
    assert facts["uptime_hours"] == "2.0"
    assert facts["free_mb"] == "2048"


def test_health_reports_no_free_space_when_df_says_nothing_usable() -> None:
    """Reporting a wrong number here would let a restore start with no room."""
    # Arrange
    transport = FakeTransport(responses={**HOST_RESPONSES, "df -k /": "Filesystem 1K-blocks Used Available Use% Mounted on"})

    # Act
    facts = actions.health(transport)

    # Assert
    assert "free_mb" not in facts


def test_remove_paths_declares_itself_destructive() -> None:
    """The policy layer keys off this. A mislabelled delete bypasses approval."""
    # Arrange
    transport = FakeTransport(responses={"rm -rf /tmp/stale": ""})

    # Act
    removed = actions.remove_paths(transport, ["/tmp/stale"])

    # Assert
    assert removed == ["/tmp/stale"]
    assert [call.effect for call in transport.calls] == [Effect.DESTRUCTIVE]


def test_remove_paths_quotes_what_it_deletes() -> None:
    """An unquoted path with a space would delete two directories."""
    # Arrange
    transport = FakeTransport()

    # Act
    actions.remove_paths(transport, ["/tmp/two words"])

    # Assert
    assert transport.commands() == ["rm -rf '/tmp/two words'"]
