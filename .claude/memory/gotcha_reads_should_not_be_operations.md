---
name: Cheap reads must not be wrapped in run_step
description: Modelling get_base_info/check_update as run_step created a tracked operation on every panel load; when the network call stalled it showed RUNNING forever and could not be cancelled.
type: project
---

During the S7 HA cutover (2026-08-04) `get_base_info` and `check_update` were implemented as `Toolkit.run_step("kodi.check_update")`. The panel calls `_loadBaseInfo()` on every load, so **every page load minted a tracked operation**. When the step's outbound HTTP call to the Kodi mirror stalled, that operation sat at RUNNING indefinitely, Cancel could not touch it, and each refresh created another one. No restart cleared it because a fresh one appeared on the next load.

Two compounding facts made it unfixable from the outside: a blocking `urllib.request.urlopen` has no cooperative cancellation checkpoint, so `handle.check_cancelled()` never runs; and a Python thread cannot be forcibly killed, so `Dispatcher.shutdown(cancel_futures=True)` only drops *queued* work, never work already in flight.

**Why:** `run_step` exists to give work an operation record, an audit trail, policy gating and cancellation. A frequently-polled read gets none of that value and pays the full cost. The predecessor's `FleetService.get_base_info`/`check_update` were plain synchronous methods returning a dict, with no operation record — the right shape, and it was a mistake to "upgrade" them.

**How to apply:** reserve `run_step`/`start_step` for work a user would want to watch, cancel, or audit. For a cheap read called on a timer or on page load, call the underlying function directly and bound it with a timeout at the adapter (`asyncio.wait_for` on the HA side). If a step *does* make a long network call, it needs an interruptible client, not just a socket timeout — a socket timeout does not cover DNS resolution stalling before the socket opens. See [[project_ha_panel_parity]].
