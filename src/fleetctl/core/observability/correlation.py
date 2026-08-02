"""Correlation ids that ride along without every caller passing them.

The engine sets the context once; a logging filter injects it into every
record. Step authors write no correlation code and cannot forget to. This is
what makes eight concurrent device operations separable in a single log.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Iterator

_UNSET = "-"


@dataclass(frozen=True, slots=True)
class Correlation:
    """Where a log line or audit record came from.

    **PARAMETERS:**
        `run_id` (str): One workflow invocation.  <br>
        `step_id` (str): One step within that run.  <br>
        `op_id` (str): One (step, device) pair.  <br>
        `actor` (str): Who initiated it, e.g. ``cli:alice`` or ``mcp:claude``.  <br>
    """

    run_id: str = _UNSET
    step_id: str = _UNSET
    op_id: str = _UNSET
    actor: str = _UNSET


_CURRENT: ContextVar[Correlation] = ContextVar("fleetctl_correlation", default=Correlation())


def current() -> Correlation:
    """RETURNS: Correlation: The correlation in effect for this context."""
    return _CURRENT.get()


@contextmanager
def correlate(**fields: str) -> Iterator[Correlation]:
    """Bind correlation fields for the duration of a block.

    Fields not supplied are inherited from the enclosing context, so an
    engine can set `run_id` once and each step add only its own `step_id`.

    **PARAMETERS:**
        `**fields` (str): Any of `run_id`, `step_id`, `op_id`, `actor`.  <br>

    **YIELDS:**
        `Correlation`: The merged correlation now in effect.  <br>
    """
    merged = replace(_CURRENT.get(), **fields)
    token = _CURRENT.set(merged)
    try:
        yield merged
    finally:
        _CURRENT.reset(token)


class CorrelationFilter(logging.Filter):
    """Attaches the current correlation to every log record.

    Installed on handlers rather than loggers so it applies to records
    emitted from libraries too.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Attach correlation fields to `record` and always keep it.

        **PARAMETERS:**
            `record` (logging.LogRecord): The record being emitted.  <br>

        **RETURNS:**
            `bool`: Always ``True`` — this filter annotates, it never drops.  <br>
        """
        active = current()
        record.run_id = active.run_id
        record.step_id = active.step_id
        record.op_id = active.op_id
        record.actor = active.actor
        return True
