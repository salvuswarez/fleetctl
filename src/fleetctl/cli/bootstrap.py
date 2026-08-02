"""The CLI's composition root: the only place this adapter constructs anything.

Everything a step touches is built here and injected. A step never reaches for
a transport, an artifact store, or an audit sink — which is what makes the
same step body runnable from Home Assistant, from a test, or from an agent
without changing a line of it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..core.artifacts.store import ArtifactStore, LocalArtifactStore
from ..core.config.loader import load_yaml_file
from ..core.config.secrets import EnvSecretProvider, SecretResolver
from ..core.errors import FleetError
from ..core.inventory.device import Device
from ..core.inventory.store import DeviceStore
from ..core.observability.audit import ChainedAuditWriter, JsonlAuditSink
from ..core.operations.registry import OperationRegistry
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


def build_container(
    *,
    config_dir: Path | None = None,
    home: Path | None = None,
    actor: str = "cli",
    registry: Registry | None = None,
) -> Container:
    """Resolve everything this invocation needs.

    **PARAMETERS:**
        `config_dir` (Path | None): Directory holding `fleet.yml` and `inventory/devices.yml`. Defaults to ``config/`` under the working directory.  <br>
        `home` (Path | None): Runtime state directory. Defaults to ``~/.fleetctl``.  <br>
        `actor` (str): Who is running this. Recorded on every audit event.  <br>
        `registry` (Registry | None): Pre-populated registry. Defaults to discovering installed packs.  <br>

    **RETURNS:**
        `Container`: The resolved dependencies.  <br>
    """
    config_dir = config_dir or DEFAULT_CONFIG_DIR
    home = home or DEFAULT_HOME

    raw = load_yaml_file(config_dir / "fleet.yml")
    config = SecretResolver(EnvSecretProvider()).resolve_all(raw)

    observability = config.get("observability", {}) if isinstance(config.get("observability"), dict) else {}
    audit_dir = Path(str(observability.get("audit_dir", home / "audit")))

    artifacts_config = config.get("artifacts", {}) if isinstance(config.get("artifacts"), dict) else {}
    artifact_root = Path(str(artifacts_config.get("local_root", home / "artifacts")))

    return Container(
        registry=registry if registry is not None else discover(),
        inventory=DeviceStore(config_dir / "inventory" / "devices.yml"),
        artifacts=LocalArtifactStore(artifact_root),
        operations=OperationRegistry(),
        audit=ChainedAuditWriter(JsonlAuditSink(audit_dir)),
        config=config,
        home=home,
        actor=actor,
        config_dir=config_dir,
    )
