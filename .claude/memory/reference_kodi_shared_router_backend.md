---
name: The Kodi fleet shares a MariaDB backend hosted on the router, outside any fleet-management repo
description: Every managed stick's Kodi points at MariaDB (shared MyVideos library + the watchedlist addon) and SMB media sources living on the router via Entware — infrastructure that fails independently of fleetctl, capture, or deploy, and whose init script hides all startup errors.
type: reference
---

Kodi's device-side config (captured into gold backups, not held in this repo) depends on shared
backend infrastructure on the router:

- **MariaDB on port 3306**, installed via Entware on the router's USB drive (`/opt`, exposed over SMB
  as the `entware` share). Two independent consumers: Kodi's own shared video library (schema
  `MyVideos<NNN>`, configured in `userdata/advancedsettings.xml`) and the separate `service.watchedlist`
  addon, which keeps its own MySQL settings in its own `settings.xml` — it is not file/SMB-backed in
  this setup. Watchedlist needs the `script.module.myconnpy` addon.
  Key paths: init script `/opt/etc/init.d/S70mysqld`, config `/opt/etc/mysql/my.cnf`, datadir
  `/opt/var/lib/mysql`.
- **SMB on port 445** — media sources (`userdata/sources.xml`).

**Why this matters:** a Kodi symptom that looks like a device/config/deploy bug ("watchedlist won't
sync", "library is empty", "can't connect") is very often this shared infrastructure being down, not
anything a fleet-management tool did. Confirmed via a real outage (2026-07-30, Asus/Merlin router):
`/opt` is a symlink into a ramdisk (`/tmp/opt`) that a firmware update wiped, along with the
`/jffs/scripts/post-mount` script that normally relinks it and starts Entware at boot — so the outage
looked like "MariaDB is broken" when it was actually "the symlink target never got recreated after a
reboot." A reboot alone would **not** have fixed it; the broken state was the post-reboot steady
state.

**Two gotchas worth knowing if debugging this again:**
1. `S70mysqld` redirects all output to `/dev/null` — a failed start produces no visible error and
   `status` just says "not running." Run the daemon binary directly, without the redirect, to see why.
2. The sticks run an always-on VPN tunnel — testing connectivity *from* a stick can't distinguish
   "server down" from "device can't route there." Test from a machine that isn't behind that tunnel.

**How to apply:** before debugging a Kodi library/watchedlist symptom as a fleetctl or deploy-pipeline
issue, TCP-test the MariaDB and SMB ports on the router directly. Kodi retries roughly a dozen schema
versions on every failed DB connect and watchedlist retries on its own interval, so a dead backend adds
real startup churn on a low-RAM device — see the texture-index gotcha for how this compounds.
