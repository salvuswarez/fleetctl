---
name: A stored device IP goes stale as the router reassigns DHCP leases
description: An inventory-recorded IP is only as fresh as the last scan — DHCP lease reassignment means a stored IP can point at a device that no longer responds, or at nothing, well before anyone edits the inventory by hand.
type: gotcha
---

Confirmed on real hardware in the predecessor repo (2026-07-30): two independent inventories tracking
the same physical fleet by MAC address disagreed on IP for two separate devices, and in both cases the
*more recently scanned* file was the one still live — the stale one didn't respond to a ping at all.

**Why:** the router reassigns DHCP leases over time; nothing about capture, build, or deploy
continuously re-verifies a stored IP against reality — a scan only refreshes whichever store it
targets, at the moment it runs.

**How to apply:** don't trust a stored IP blindly when a device seems unreachable or behaves
unexpectedly — reconcile by MAC first, then verify with a live probe (ping / ADB handshake) before
capturing or deploying against it. Prefer re-running discovery/scan over hand-editing an IP. This
matters more once there is exactly one inventory (post-cutover, `core/inventory` is the sole store) —
there is no longer a second file to cross-check against, so a stale entry has nothing to disagree
with and won't surface itself; it just fails quietly at the next real operation.
