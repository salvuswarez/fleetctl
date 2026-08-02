"""Workflows: named, ordered step sequences with declarative targeting.

The predecessor's pipeline was implicit — you knew to run capture, then
build, then deploy because the documentation said so. Nothing recorded the
ordering, nothing expressed "every device tagged kodi", and a fleet-wide run
had no vocabulary for concurrency or what to do when one device fails.

Deliberately *not* a template language. Artifact handoff between steps works
by querying the store for the newest artifact of a kind, which is behaviour
the steps need anyway — adding `{{ }}` interpolation would mean owning an
expression parser, a scoping model, and a debugging story with no debugger,
to solve a problem that is already solved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..config.loader import load_yaml_file, load_yaml_text
from ..errors import ConfigError
from ..inventory.device import Device


class OnError(str, Enum):
    """What a workflow does when one step fails."""

    CONTINUE = "continue"
    STOP = "stop"


@dataclass(frozen=True, slots=True)
class Target:
    """Which devices a step runs against.

    An empty target means fleet-level: the step runs once, with no device.

    **PARAMETERS:**
        `tags` (tuple[str, ...]): Every tag a device must carry.  <br>
        `device_type` (str): Device pack id a device must have; empty matches any.  <br>
        `ids` (tuple[str, ...]): Explicit device ids. When set, tags and type are ignored.  <br>
        `none` (bool): Explicitly fleet-level, even if other fields were given.  <br>
    """

    tags: tuple[str, ...] = ()
    device_type: str = ""
    ids: tuple[str, ...] = ()
    none: bool = False

    @property
    def is_fleet_level(self) -> bool:
        """RETURNS: bool: Whether this step runs once rather than per device."""
        return self.none or not (self.tags or self.device_type or self.ids)

    def select(self, devices: Sequence[Device]) -> list[Device]:
        """Resolve this target against the fleet.

        **PARAMETERS:**
            `devices` (Sequence[Device]): The known fleet.  <br>

        **RETURNS:**
            `list[Device]`: Matching devices, in inventory order. Empty for a fleet-level target.  <br>
        """
        if self.is_fleet_level:
            return []
        if self.ids:
            wanted = set(self.ids)
            return [device for device in devices if device.id in wanted]
        return [device for device in devices if all(device.has_tag(tag) for tag in self.tags) and (not self.device_type or device.type == self.device_type)]

    @classmethod
    def parse(cls, raw: Any) -> Target:
        """Build a target from a workflow's `targets:` block.

        **PARAMETERS:**
            `raw` (Any): ``"none"``, or a mapping with `tags`, `type`, `ids`.  <br>

        **RETURNS:**
            `Target`: The parsed target.  <br>

        **RAISES:**
            `ConfigError`: If the block is neither of those shapes.  <br>
        """
        if raw is None or raw == "none":
            return cls(none=True)
        if not isinstance(raw, Mapping):
            raise ConfigError(f"targets must be 'none' or a mapping, got {raw!r}", key="targets")
        return cls(
            tags=tuple(raw.get("tags", ())),
            device_type=str(raw.get("type", "")),
            ids=tuple(raw.get("ids", ())),
        )


@dataclass(frozen=True, slots=True)
class WorkflowStep:
    """One step within a workflow.

    **PARAMETERS:**
        `id` (str): Identifier within the workflow, for reporting.  <br>
        `use` (str): Registered step id to run, e.g. ``kodi.deploy``.  <br>
        `target` (Target): Which devices it runs against.  <br>
        `params` (Mapping[str, Any]): The step's `with:` block, layered above device config.  <br>
        `concurrency` (int): How many devices to process at once.  <br>
        `on_error` (OnError): Whether a failure stops the workflow.  <br>
    """

    id: str
    use: str
    target: Target = field(default_factory=Target)
    params: Mapping[str, Any] = field(default_factory=dict)
    concurrency: int = 1
    on_error: OnError = OnError.STOP


@dataclass(frozen=True, slots=True)
class Workflow:
    """A named sequence of steps.

    **PARAMETERS:**
        `name` (str): Workflow name, used to invoke it.  <br>
        `description` (str): What it is for.  <br>
        `steps` (tuple[WorkflowStep, ...]): Steps, in order.  <br>
    """

    name: str
    description: str = ""
    steps: tuple[WorkflowStep, ...] = ()

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], *, source: str = "<mapping>") -> Workflow:
        """Build a workflow from parsed YAML.

        **PARAMETERS:**
            `raw` (Mapping[str, Any]): The parsed document.  <br>
            `source` (str): Name used in error messages.  <br>

        **RETURNS:**
            `Workflow`: The parsed workflow.  <br>

        **RAISES:**
            `ConfigError`: If the document is missing a name, has no steps, or a step omits `use`.  <br>
        """
        name = str(raw.get("name", "")).strip()
        if not name:
            raise ConfigError(f"{source}: a workflow needs a name", key="name")

        raw_steps = raw.get("steps")
        if not isinstance(raw_steps, Sequence) or not raw_steps:
            raise ConfigError(f"{source}: workflow {name!r} has no steps", key="steps")

        steps: list[WorkflowStep] = []
        for index, entry in enumerate(raw_steps):
            if not isinstance(entry, Mapping):
                raise ConfigError(f"{source}: step {index} is not a mapping", key="steps")
            use = str(entry.get("use", "")).strip()
            if not use:
                raise ConfigError(f"{source}: step {index} is missing 'use'", key="steps")
            steps.append(
                WorkflowStep(
                    id=str(entry.get("id", use)),
                    use=use,
                    target=Target.parse(entry.get("targets")),
                    params=dict(entry.get("with", {})),
                    concurrency=max(1, int(entry.get("concurrency", 1))),
                    on_error=OnError(str(entry.get("on_error", OnError.STOP.value))),
                )
            )
        return cls(name=name, description=str(raw.get("description", "")), steps=tuple(steps))

    @classmethod
    def from_yaml(cls, text: str, *, source: str = "<string>") -> Workflow:
        """RETURNS: Workflow: A workflow parsed from YAML text."""
        return cls.from_mapping(load_yaml_text(text, source=source), source=source)

    @classmethod
    def from_file(cls, path: Path) -> Workflow:
        """RETURNS: Workflow: A workflow parsed from a YAML file.

        **RAISES:**
            `ConfigError`: If the file is missing or malformed.  <br>
        """
        if not path.is_file():
            raise ConfigError(f"No such workflow file: {path}", key=str(path))
        return cls.from_mapping(load_yaml_file(path), source=str(path))


def load_workflows(directory: Path) -> dict[str, Workflow]:
    """Load every workflow in a directory.

    **PARAMETERS:**
        `directory` (Path): Directory holding ``*.yml`` workflow files.  <br>

    **RETURNS:**
        `dict[str, Workflow]`: Workflows by name. An absent directory yields an empty mapping.  <br>

    **RAISES:**
        `ConfigError`: If a file is malformed, or two files declare the same name.  <br>
    """
    found: dict[str, Workflow] = {}
    if not directory.is_dir():
        return found
    for path in sorted(directory.glob("*.yml")):
        workflow = Workflow.from_file(path)
        if workflow.name in found:
            raise ConfigError(f"Duplicate workflow name {workflow.name!r} in {path}", key=str(path))
        found[workflow.name] = workflow
    return found
