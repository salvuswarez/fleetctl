---
name: a transport cannot answer for a pack's capabilities
description: state and apps are built by pack managers, so checking the transport alone rejected steps the pack could run; wire verbs stay the transport's to answer.
type: project
---

`check_capabilities` compared a step's `requires` against
`transport.capabilities()` alone. That worked while every transport served one
pack — `AdbTransport` declares state, apps and settings, so Android was fine.
It broke the moment `SshTransport` served two packs: `kodi.capture` on a Steam
Deck failed with *"requires unsupported capabilities: state"* even though
`SteamDeckPack` supplies a state manager.

The split that actually holds:

| Kind | Authority | Verbs |
|---|---|---|
| Wire | the transport performs them | `reach` `facts` `exec` `files` `power` |
| Derived | a pack's managers build them on the wire verbs | `state` `apps` `settings` `cleanup` |

`WIRE_CAPABILITIES` in `core/effects.py` names the first set. The check is
`transport.capabilities() | (pack.capabilities - WIRE_CAPABILITIES)`: a pack
adds only what it implements and can never claim `exec` on a dead connection.
A first attempt used a plain union and a test caught it — that let a pack
paper over a transport that could do nothing at all.

Related, same root: `SshTransport` raised `DeviceUnauthorizedError` both for a
refused credential and for a host absent from `known_hosts`. `claim_host`
reads that as "reached but refused — needs key approval" and writes an
inventory entry, so every stranger on the subnet with port 22 open became a
fleet device, the router included. An unknown host key is now a plain
`TransportError`, which discovery already treats as "not mine".

**Why:** both bugs come from one thing — a transport shared by packs of
differing capability cannot speak for any of them.

**How to apply:** when a second pack starts sharing a transport, re-check
anything that asks the transport a question about the *device*. See
[[architecture_rings_and_decisions]].
