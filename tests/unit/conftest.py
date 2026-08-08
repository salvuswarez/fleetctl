"""Shared fixtures for device-pack tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Protocol

import pytest

from fleetctl.core.artifacts.store import LocalArtifactStore
from fleetctl.core.inventory.device import Device
from fleetctl.core.inventory.store import DeviceStore
from fleetctl.core.observability.audit import ChainedAuditWriter, InMemoryAuditSink
from fleetctl.core.operations.registry import OperationRegistry
from fleetctl.core.transport.auditing import AuditingTransport
from fleetctl.core.transport.base import Transport
from fleetctl.core.workflow.step import DeviceStepContext
from fleetctl.packs.android.appmgr import AndroidAppManager
from fleetctl.packs.android.quirks import AndroidQuirks
from fleetctl.packs.android.state import AndroidStateManager


class DeviceContextFactory(Protocol):
    """Builds a device step context around a transport."""

    def __call__(
        self,
        transport: Transport,
        *,
        device_type: str = "firetv",
        config: dict[str, Any] | None = None,
        quirks: AndroidQuirks | None = None,
    ) -> DeviceStepContext: ...


@pytest.fixture
def device_context(tmp_path: Path) -> DeviceContextFactory:
    """Assemble a device step context, matching what a real run receives.

    The transport is wrapped for auditing, exactly as the composition root
    does it, so a pack test exercises the same path production takes.

    **RETURNS:**
        `DeviceContextFactory`: Call it with a transport to get a context.  <br>
    """

    def _build(
        transport: Transport,
        *,
        device_type: str = "firetv",
        config: dict[str, Any] | None = None,
        quirks: AndroidQuirks | None = None,
    ) -> DeviceStepContext:
        audited = AuditingTransport(transport, ChainedAuditWriter(InMemoryAuditSink()))
        device = Device(id=f"{device_type}-1", type=device_type, address="192.168.1.50", name="Test Device")
        inventory = DeviceStore(tmp_path / "devices.yml")
        inventory.save([device])
        registry = OperationRegistry()
        return DeviceStepContext(
            device=device,
            transport=audited,
            state=AndroidStateManager(audited, quirks or AndroidQuirks()),
            apps=AndroidAppManager(audited, quirks or AndroidQuirks()),
            artifacts=LocalArtifactStore(tmp_path / "store"),
            inventory=inventory,
            config=config or {},
            handle=registry.start("op-test", "test.step", device.id),
            workspace=tmp_path / "ws",
        )

    return _build
