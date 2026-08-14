---
name: a sleeping Steam Deck answers ping but drops TCP
description: Wifi power-save leaves ICMP replying while SSH connects time out; the first connect after idle fails and an immediate retry succeeds.
type: reference
---

An idle Steam Deck on wifi keeps answering ICMP — ping replies normally, and
in fact *faster* than when awake (4-20ms versus ~56ms, since the radio is not
power-cycling) — while TCP connections to port 22 **time out**. A second
attempt moments later connects instantly.

Observed 2026-08-06 mid-session: a capture that had just succeeded failed on
the next run with `TransportError: Could not reach ... over SSH: timed out`,
while ping showed 0% loss.

Note the three states are distinguishable and mean different things:

| Symptom | Meaning |
|---|---|
| Ping fails | Off, or off the network |
| Ping OK, TCP 22 **refused** | Awake, `sshd` not running (Remote Access off) |
| Ping OK, TCP 22 **times out** | Asleep / wifi power-save — retry |

**Why:** "responds to ping" reads as "reachable" and is not, on this hardware.
Anything that decides a device is unreachable from ICMP alone will be wrong
about a Deck, and `SshTransport.connect()` has no retry — the first call after
idle can legitimately fail with nothing broken.

**How to apply:** treat a connect timeout to a Deck as retryable, not as a
dead host; a refused connection is the one that means "SSH is off". This is a
candidate for a bounded connect retry in `SshTransport`, which has not been
added. See [[project_steamdeck_kodi_pack_plan]] and
[[gotcha_inventory_ip_drift_from_dhcp]] for the related "verify before
trusting" lesson.
