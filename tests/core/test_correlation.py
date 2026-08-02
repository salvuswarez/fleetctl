"""Tests for correlation context propagation."""

from __future__ import annotations

import logging

from fleetctl.core.observability.correlation import CorrelationFilter, correlate, current


def test_fields_are_unset_by_default() -> None:
    # Act
    active = current()

    # Assert
    assert active.run_id == "-"
    assert active.actor == "-"


def test_nested_blocks_inherit_unspecified_fields() -> None:
    """An engine sets `run_id` once; each step adds only its own `step_id`."""
    # Arrange / Act
    with correlate(run_id="r1", actor="cli:alice"):
        with correlate(step_id="s1"):
            inner = current()

    # Assert
    assert (inner.run_id, inner.step_id, inner.actor) == ("r1", "s1", "cli:alice")


def test_context_is_restored_on_exit() -> None:
    # Arrange / Act
    with correlate(run_id="r1"):
        pass

    # Assert
    assert current().run_id == "-"


def test_filter_annotates_records_and_never_drops_them() -> None:
    # Arrange
    log_filter = CorrelationFilter()
    record = logging.LogRecord("fleetctl.test", logging.INFO, __file__, 1, "msg", None, None)

    # Act
    with correlate(run_id="r1", op_id="o1"):
        kept = log_filter.filter(record)

    # Assert
    assert kept is True
    assert getattr(record, "run_id") == "r1"
    assert getattr(record, "op_id") == "o1"
