"""The scan step: discovery as something a workflow or an agent can run."""

from __future__ import annotations

import logging

from fleetctl.core.effects import Effect
from fleetctl.core.errors import FleetError
from fleetctl.core.registry import RegisteredStep
from fleetctl.core.workflow.step import DiscoveryStepContext, StepResult, StepSpec

LOGGER = logging.getLogger(__name__)

PROVIDER = "core"

SCAN = StepSpec(
    id="fleet.scan",
    summary="Sweep a subnet and merge the devices that answer into the inventory.",
    effect=Effect.MUTATING,
    requires=frozenset(),
    scope="discovery",
)


def scan(context: DiscoveryStepContext) -> StepResult:
    """Discover devices on a subnet and record them.

    **PARAMETERS:**
        `context` (DiscoveryStepContext): Carries the scanner and the resolved config. `subnet` is required; `dry_run` reports without writing.  <br>

    **RETURNS:**
        `StepResult`: Facts carry what answered, what was identified, what refused this key, and what changed.  <br>

    **RAISES:**
        `FleetError`: If no subnet was given, or no device packs are installed.  <br>
    """
    subnet = str(context.config.get("subnet", "")).strip()
    if not subnet:
        raise FleetError("fleet.scan needs a subnet, e.g. --set subnet=192.168.1.0/24")

    outcome = context.scanner.run(subnet, dry_run=bool(context.config.get("dry_run", False)), log=context.handle.log)

    # Refused keys are the one discovery result a user can act on, so they go
    # in the timeline rather than only in the facts.
    if outcome.unauthorized:
        context.handle.log(f"{len(outcome.unauthorized)} host(s) reachable but refused this key: {', '.join(outcome.unauthorized)}")

    return StepResult(summary=outcome.summary(), facts=outcome.facts())


def steps() -> list[RegisteredStep]:
    """RETURNS: list[RegisteredStep]: Steps that belong to no pack, because every fleet has them."""
    return [RegisteredStep(spec=SCAN, run=scan, provider=PROVIDER)]
