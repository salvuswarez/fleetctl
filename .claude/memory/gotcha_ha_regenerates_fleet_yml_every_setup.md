---
name: gotcha_ha_regenerates_fleet_yml_every_setup
description: The HA integration rewrites its own fleet.yml on every setup, so device protection cannot be hand-edited there — it hangs off inventory tags instead.
metadata:
  type: project
---

The HA integration is a **separate composition root** with its own
`config_dir` (`hass.config.path("fleetctl_config")`) and `home`
(`fleetctl_home`). A `protected:` rule added to the repo's `config/fleet.yml`
governs the CLI only and has no effect on anything the panel does.

Worse, `_write_fleet_yml` **regenerates** that fleet.yml from the config entry
on every setup. Its own docstring says a hand-added block "is gone on the next
reload." As shipped, the generated policy was:

```python
"policy": {"actors": {"ha:*": {"allow": ["*"]}}}
```

No `protected` block at all — so `ha:*` could reach every device
unconditionally, with no confirm on destructive. That falsified the S4 exit
criterion ("a device marked protected cannot be reached by any actor without a
config edit") for the entire HA surface, which is most real usage.

**Why:** the config entry is deliberately the source of truth so an
options-flow edit takes effect without hand-editing YAML. Protection was
simply never added to the generated payload.

**How to apply:** protect a device by **tagging** it, never by editing
fleet.yml. `PROTECTED_TAGS` in the integration turns tags into
`policy.protected` rules on every setup — `gold` denies `kodi.deploy` and
`*.maintain` while still allowing `kodi.capture`; `protected` denies `*`.
Tags are the right anchor because `inventory/devices.yml` is the one file a
reload leaves alone. Rules are emitted unconditionally, so tagging a device
later needs no reload.

When reasoning about whether an action is permitted, always ask **which
composition root** — CLI and HA resolve different policies from different
files. Related: [[feedback_gold_device_protection]],
[[gotcha_adb_key_identity_mismatch]].
