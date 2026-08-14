---
name: a device with two interfaces reports two MACs and used to become two records
description: The Shield answered discovery over ethernet on one scan and wifi on another, so the inventory grew a second record with the same id, serial and address but a different MAC. Matching now lets the serial outrank a changed MAC.
metadata:
  type: project
---

Found 2026-08-13 in the live HA inventory: two `shield` records differing in
exactly one field — the MAC's last octet. Same id, same serial, same address.
A Shield (or any box with both ethernet and wifi) reports whichever
interface answered, so a MAC is not a device identity, it is an interface
identity.

`reconcile._matches` used to return on the MAC comparison the moment both
sides had one, so a changed MAC read as a different device and discovery
appended a second record. The serial now wins when the two disagree; two
devices with differing MACs and *no* serial still stay separate, because a
reused DHCP lease is the ordinary explanation and there is no evidence there.

Existing duplicates could not be cleared by scanning either — matching found
only the first record, updated it, and wrote both back, so a manual deletion
was undone by the next sweep. `reconcile` now collapses the stored fleet
before merging discovery and again afterwards.

**Why:** the pair looked identical at a glance, which sent the first
investigation after the HA migration path instead of the matching rule.
One field of difference is the whole story.

**How to apply:** when a device appears twice, diff the two records field by
field before assuming a write path duplicated them. If they differ only in
MAC, it is one box with two interfaces. See
[[gotcha_inventory_ip_drift_from_dhcp]].
