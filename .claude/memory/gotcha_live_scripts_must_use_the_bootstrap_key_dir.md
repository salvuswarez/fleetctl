---
name: gotcha_live_scripts_must_use_the_bootstrap_key_dir
description: A hand-written live script that picks its own ADB key directory presents a different key than the CLI, so authorizing it on the device buys nothing.
metadata:
  type: project
---

`cli/bootstrap.py` hands packs `{"key_dir": home / "keys"}` — so the CLI
presents `~/.fleetctl/keys`. A live script that constructs `AdbKeyStore` with
any other path (`~/.fleetctl/.adb_keys` is an easy guess, and matches the
`.gitignore` entry) generates a **second** key pair on first use.

The device then shows an authorization prompt for that script's key. Accepting
it authorizes only that key. The CLI still fails auth, looking exactly like a
device problem.

The HA integration is a third identity again (`fleetctl_home/keys`), so
accepting a prompt raised by the panel does not authorize the CLI either.
`~/.fleetctl/keys-unused-20260802` is a fossil of this going wrong before.

**Why:** the key directory is a composition-root decision, and a hand-written
script is standing in for the composition root without inheriting its choices.

**How to apply:** in any script under `.claude/temp/`, set
`KEY_DIR = Path.home() / ".fleetctl" / "keys"` and say in a comment that it
must match `bootstrap.py`. Before blaming a device for an auth timeout, check
which key directory the failing caller used. Related:
[[gotcha_adb_key_identity_mismatch]],
[[gotcha_ha_regenerates_fleet_yml_every_setup]].
