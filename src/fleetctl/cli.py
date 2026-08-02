"""Command-line entry point.

Deliberately thin: this is one of several port adapters over the same core
(alongside the Home Assistant integration and, later, an MCP server). Once
the step registry exists, commands are generated from registered steps
rather than hand-written here.
"""

from __future__ import annotations

import logging
import sys

import click

from ._version import get_version

LOGGER = logging.getLogger(__name__)

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def configure_logging(verbose: int) -> None:
    """Send diagnostic logging to stderr at a level chosen by `-v` repetition.

    **PARAMETERS:**
        `verbose` (int): Count of ``-v`` flags. ``0`` shows warnings and worse, ``1`` adds info, ``2`` or more adds debug.  <br>
    """
    level = {0: logging.WARNING, 1: logging.INFO}.get(verbose, logging.DEBUG)
    # No `force=True`: basicConfig is a no-op when the root logger already has
    # handlers, which is what keeps an embedding host's logging setup intact
    # when fleetctl is used as a library. The cost is that a second in-process
    # invocation keeps the first call's level.
    logging.basicConfig(level=level, format=_LOG_FORMAT, stream=sys.stderr)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(get_version(), "-V", "--version", prog_name="fleetctl")
@click.option("-v", "--verbose", count=True, help="Increase log verbosity; repeat for debug.")
def main(verbose: int) -> None:
    """Manage a fleet of home devices."""
    configure_logging(verbose)


if __name__ == "__main__":
    main()
