---
name: a fresh install's ADB key is not authorized, so the first scan finds nothing
description: fleetctl mints its own key at ~/.fleetctl/keys. Devices that trust a different key silently fail to probe, and the scan reports them as unrecognized rather than unauthorized.
type: project
---

On a fresh install `AdbKeyStore` generates a new RSA pair at
`~/.fleetctl/keys/adbkey`. Devices that were paired against a *different*
key — the predecessor's `~/.fire_tools/adb_keys/`, or the Home Assistant
integration's own store — do not trust it, so the auth handshake fails and
`probe()` returns `None`. The scan then reports the host as **unrecognized**,
which reads identically to "not a device I support".

Observed 2026-08-02 on the live network: the sweep found the hosts, ADB port
5555 was open on four of them, and nothing was claimed until the trusted key
was put in place.

**Two ways out.** Either authorize the new key on each device (an on-screen
prompt per device), or reuse a key the devices already trust:

```bash
cp ~/.fire_tools/adb_keys/adbkey* ~/.fleetctl/keys/
```

**How to diagnose:** if a scan reports hosts as unrecognized, check whether
the ADB port is actually open before assuming the pack is at fault. An open
port plus no claim almost always means authorization, not detection:

```bash
timeout 3 bash -c 'echo > /dev/tcp/<address>/5555' && echo open
```

**Worth fixing:** the scan cannot currently tell "did not answer" from
"refused to authorize", and those need different actions from the user. The
transport raises `TransportError` in both cases. Distinguishing them — and
saying "N host(s) have ADB open but did not authorize this key" — would turn
a confusing empty result into an actionable one. See
[[gotcha_adb_key_identity_mismatch]] for the same problem between the CLI and
the HA integration.
