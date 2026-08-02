"""fleetctl — plugin-based fleet management for home devices.

Three rings, with dependencies pointing inward only:

- ``core`` — device-agnostic kernel: transport, inventory, discovery,
  artifacts, operations, workflow, config, observability.
- ``packs`` — device types (what a device *is* and what you can do to it).
- ``apps`` — software running on devices (Kodi and friends).

An app pack never imports a device pack: it declares the capabilities it
needs and the engine resolves which pack provides them.

This module is intentionally empty of code. Every ``__init__.py`` in the
package holds a docstring and nothing else, so that importing any part of
``fleetctl`` cannot trigger side effects. The version lives in
``fleetctl._version``.
"""

from __future__ import annotations
