"""The CLI's composition root: the only place this adapter constructs anything.

Everything a step touches is built here and injected. A step never reaches for
a transport, an artifact store, or an audit sink — which is what makes the
same step body runnable from Home Assistant, from a test, or from an agent
without changing a line of it.
"""

from __future__ import annotations

import getpass
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from ..core.artifacts.store import ArtifactStore, LocalArtifactStore
from ..core.config.loader import load_yaml_file
from ..core.config.secrets import EnvSecretProvider, SecretResolver
from ..core.errors import FleetError, TransportError
from ..core.inventory.device import Device
from ..core.inventory.store import DeviceStore
from ..core.observability.audit import ChainedAuditWriter, JsonlAuditSink
from ..core.operations.registry import OperationRegistry
from ..core.policy import Policy, load_policy
from ..core.registry import Registry, discover
from ..core.state import StateManager
from ..core.transport.auditing import AuditingTransport
from ..core.transport.base import Transport
from ..core.workflow.workflow import Workflow, load_workflows

LOGGER = logging.getLogger(__name__)

DEFAULT_HOME = Path.home() / ".fleetctl"
DEFAULT_CONFIG_DIR = Path("config")


@dataclass(frozen=True, slots=True)
class Container:
    """Resolved dependencies for one CLI invocation.

    **PARAMETERS:**
        `registry` (Registry): Discovered packs and their steps.  <br>
        `inventory` (DeviceStore): The known fleet.  <br>
        `artifacts` (ArtifactStore): Where artifacts live.  <br>
        `operations` (OperationRegistry): Operation tracking for this process.  <br>
        `audit` (ChainedAuditWriter): Where effects are recorded.  <br>
        `config` (Mapping[str, Any]): Fleet-level configuration, secrets resolved.  <br>
        `home` (Path): Runtime state directory.  <br>
        `actor` (str): Who is running this, recorded on every audit event.  <br>
    """

    registry: Registry
    inventory: DeviceStore
    artifacts: ArtifactStore
    operations: OperationRegistry
    audit: ChainedAuditWriter
    config: Mapping[str, Any]
    home: Path
    actor: str
    config_dir: Path

    @property
    def staging_root(self) -> Path:
        """RETURNS: Path: Parent directory for per-operation workspaces."""
        return self.home / "staging"

    @property
    def failures_root(self) -> Path:
        """RETURNS: Path: Where a failed operation's workspace is preserved."""
        return self.home / "forensics"

    @property
    def policy(self) -> Policy:
        """RETURNS: Policy: The configured policy, or a permissive one when `fleet.yml` has no `policy:` block."""
        return load_policy(self.config)

    def workflows(self) -> dict[str, Workflow]:
        """Every available workflow, shipped ones first.

        **RETURNS:**
            `dict[str, Workflow]`: By name. A user-defined workflow shadows a shipped one, so shipping a workflow never takes an option away.  <br>
        """
        available: dict[str, Workflow] = {}
        for app in self.registry.app_packs():
            for workflow in getattr(app, "workflows", list)():
                available[workflow.name] = workflow
        available.update(load_workflows(self.config_dir / "workflows"))
        return available

    @property
    def inventory_path(self) -> Path:
        """RETURNS: Path: The inventory file, so a user can be told where to edit it."""
        return self.config_dir / "inventory" / "devices.yml"

    def connector(self) -> Callable[[str, str], Transport]:
        """Build the callback discovery uses to reach a candidate host.

        Discovery does not know what a host is yet, so it cannot ask a
        device's pack for a transport. Instead it asks by *platform*, and the
        first installed pack for that platform supplies one.

        **RETURNS:**
            `Callable[[str, str], Transport]`: Takes an address and a platform; raises `TransportError` if no transport can be opened.  <br>
        """
        settings = {"key_dir": self.home / "keys", "audit": self.audit}

        def _connect(address: str, pack_platform: str) -> Transport:
            for pack in self.registry.device_packs():
                factory = getattr(pack, "transport_for", None)
                if pack.platform != pack_platform or factory is None:
                    continue
                candidate = Device(id="probe", type=pack.id, address=address)
                return AuditingTransport(factory(candidate, settings), self.audit)
            raise TransportError(f"No installed pack provides a {pack_platform!r} transport", target=address)

        return _connect

    def transport_for(self, device: Device) -> Transport:
        """Open an audited transport to a device.

        The returned transport is already wrapped, so a step cannot bypass
        auditing — it never constructs one itself.

        **PARAMETERS:**
            `device` (Device): The target.  <br>

        **RETURNS:**
            `Transport`: A connected, audited transport. Close it when done.  <br>

        **RAISES:**
            `FleetError`: If the device's pack is unknown or provides no transport.  <br>
        """
        pack = self.registry.device_pack(device.type)
        factory = getattr(pack, "transport_for", None)
        if factory is None:
            raise FleetError(f"Device pack {device.type!r} provides no transport")
        settings = {"key_dir": self.home / "keys", "audit": self.audit}
        return AuditingTransport(factory(device, settings), self.audit)

    def state_for(self, device: Device, transport: Transport) -> StateManager:
        """RETURNS: StateManager: The device pack's state manager for this device.

        **RAISES:**
            `FleetError`: If the pack does not implement the `state` verb.  <br>
        """
        pack = self.registry.device_pack(device.type)
        factory = getattr(pack, "state_manager", None)
        if factory is None:
            raise FleetError(f"Device pack {device.type!r} does not support state snapshot/restore")
        manager: StateManager = factory(transport)
        return manager


def cli_actor() -> str:
    """Identify who is running the CLI.

    Recorded on every audit event and matched against policy patterns like
    ``cli:*``. A trail that says only "cli" cannot answer who ran something,
    which is half the point of keeping one.

    **RETURNS:**
        `str`: ``cli:<username>``, falling back to ``cli:unknown`` where the OS will not say.  <br>
    """
    try:
        return f"cli:{getpass.getuser()}"
    except Exception:  # noqa: BLE001 - no user name is not a reason to refuse to run
        return "cli:unknown"


def _under_home(configured: Any, home: Path, default_name: str) -> Path:
    """Resolve a configured directory, treating a relative path as under `home`.

    Resolving against the working directory instead would make where state
    lands depend on where the command was run from, which is how a test — or
    a user — ends up scattering audit files across a filesystem.

    **PARAMETERS:**
        `configured` (Any): The configured path, or None.  <br>
        `home` (Path): Runtime state directory.  <br>
        `default_name` (str): Subdirectory to use when nothing is configured.  <br>

    **RETURNS:**
        `Path`: An absolute-or-home-relative directory.  <br>
    """
    if configured is None:
        return home / default_name
    path = Path(str(configured))
    return path if path.is_absolute() else home / path


def build_container(
    *,
    config_dir: Path | None = None,
    home: Path | None = None,
    actor: str | None = None,
    registry: Registry | None = None,
) -> Container:
    """Resolve everything this invocation needs.

    **PARAMETERS:**
        `config_dir` (Path | None): Directory holding `fleet.yml` and `inventory/devices.yml`. Defaults to ``config/`` under the working directory.  <br>
        `home` (Path | None): Runtime state directory. Defaults to ``~/.fleetctl``.  <br>
        `actor` (str | None): Who is running this, recorded on every audit event. Defaults to `cli_actor()`.  <br>
        `registry` (Registry | None): Pre-populated registry. Defaults to discovering installed packs.  <br>

    **RETURNS:**
        `Container`: The resolved dependencies.  <br>
    """
    config_dir = config_dir or DEFAULT_CONFIG_DIR
    home = home or DEFAULT_HOME

    raw = load_yaml_file(config_dir / "fleet.yml")
    config = SecretResolver(EnvSecretProvider()).resolve_all(raw)

    observability = config.get("observability", {}) if isinstance(config.get("observability"), dict) else {}
    audit_dir = _under_home(observability.get("audit_dir"), home, "audit")

    artifacts_config = config.get("artifacts", {}) if isinstance(config.get("artifacts"), dict) else {}
    artifact_root = _under_home(artifacts_config.get("local_root"), home, "artifacts")

    return Container(
        registry=registry if registry is not None else discover(),
        inventory=DeviceStore(config_dir / "inventory" / "devices.yml"),
        artifacts=LocalArtifactStore(artifact_root),
        operations=OperationRegistry(),
        audit=ChainedAuditWriter(JsonlAuditSink(audit_dir)),
        config=config,
        home=home,
        actor=actor or cli_actor(),
        config_dir=config_dir,
    )
