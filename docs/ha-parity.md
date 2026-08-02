# Home Assistant Parity

The `firetools` integration in `salvuswarez/ha-cyberpunk` drives its panel
through 21 websocket commands, each a thin wrapper over one `fire_tools`
`FleetService` method. Nothing may be cut over until every one of them has an
equivalent here — a panel button that silently does nothing is worse than a
panel button that is missing.

This is that mapping, audited against `custom_components/firetools/ws_api.py`.

<hr>

## Reads

| Panel command | `FleetService` | fleetctl |
|---|---|---|
| `list_devices` | `list_devices()` | `Toolkit.list_devices()` |
| `list_operations` | `list_operations()` | `Toolkit.list_operations()` |
| `get_operation` | `get_operation(id)` | `Toolkit.get_operation(id)` |
| `list_backups` | `list_backups()` | `Toolkit.list_artifacts(kind)` |
| `get_base_info` | `get_base_info()` | `kodi.check_update` facts (`current`) |
| `check_update` | `check_update()` | `kodi.check_update` facts (`current`, `latest`, `update_available`) |
| — | `is_known_device(ip)` | `Toolkit.list_devices()`, or `container.inventory.get(id)` |

`get_base_info` and `check_update` collapse into one step: the predecessor's
`get_base_info` returned a subset of what `check_update` already returns.

## Device actions

| Panel command | `FleetService` | fleetctl |
|---|---|---|
| `check_device` | `check_device(ip)` | `firetv.check` / `shield.check` |
| `capture` | `start_capture(ip)` | `kodi.capture` |
| `build` | `start_build()` | `kodi.build` |
| `deploy` | `start_deploy(ip)` | `kodi.deploy` |
| `maintain` | `start_maintain(ip)` | `firetv.maintain` / `shield.maintain` |
| `capture_base` | `start_capture_base()` | `kodi.fetch_base` |
| `scan` | `start_scan(subnet)` | `fleet.scan` |

## Fleet actions

| Panel command | `FleetService` | fleetctl |
|---|---|---|
| `deploy_all` | `deploy_all()` | `kodi-deploy-all` workflow |
| `maintain_all` | `maintain_all()` | `fleet-maintenance` workflow |

Fan-out is a workflow here rather than a method. The workflow decides its own
targets from tags, so adding a device to the fleet does not mean editing the
integration.

## Operation control

| Panel command | `FleetService` | fleetctl |
|---|---|---|
| `cancel_operation` | `cancel_operation(id)` | `Toolkit.cancel_operation(id)` |
| `rerun_operation` | `rerun_operation(id)` | `Toolkit.rerun_operation(id)` |

Both keep the predecessor's semantics: cancel is a request the work observes
at its next step boundary, never a kill; rerun mints a new operation and
leaves the original's logs intact.

<hr>

## Differences the integration must account for

**Policy gating.** Every mutating call can raise `ApprovalRequired` or
`PolicyDenied`, which `FleetService` had no concept of. The integration must
surface these rather than treating them as generic failures — a panel that
reports "failed" when the answer was "ask first" trains people to retry.

**Rerun is re-gated.** Approving a destructive step once does not license
repeating it, so `rerun_operation` on a gated step raises `ApprovalRequired`
even though the original run was approved.

**Operations are per-process.** The registry is in memory, so the integration
must hold one container for the life of the config entry. A fresh container
per request would lose every operation id the panel is tracking.

**Facts, not just summaries.** `run_step` returns a `facts` mapping alongside
the human-readable summary. The panel should read `facts` for anything it
renders as data — versions, counts, addresses.

**Synchronous by default.** `FleetService.start_*` dispatched to a thread pool
and returned an id immediately. `Toolkit.run_step` runs to completion. The
integration owns its own dispatch, and should pass the op id back to the panel
from `run_step`'s return value.
