---
name: SteamOS ships no hostname binary
description: `hostname` exits 127 on SteamOS 3.8; read a host's name with `uname -n` instead, which is POSIX and always present.
type: reference
---

SteamOS 3.8.24 does not ship the `hostname` binary — it lives in the
`inetutils` package, which is absent. Running it exits 127.

This bit `packs/posix/actions.py:read_facts`, which used `hostname` and read
facts through `exec_ok` (returns `""` on failure by design). The result was a
silent gap: every other fact came back correctly and `name` simply vanished,
with no error anywhere. Found on live hardware 2026-08-06, not in tests — the
`FakeTransport` fixture had `hostname` scripted, so the suite was green.

Fixed by reading the name with `uname -n`, which is POSIX, always present, and
was already being called twice for `-r` and `-m`.

**Why:** it is a worked example of `exec_ok`'s failure mode. Swallowing errors
is right for an optional fact, but it means a missing *binary* and a host that
genuinely has no name are indistinguishable — and a test double scripted from
assumptions will never surface the difference.

**How to apply:** prefer POSIX-guaranteed commands in any probe that sweeps
hosts of unknown provenance. When a fact silently goes missing against real
hardware, suspect a missing binary before suspecting parsing. See
[[project_steamdeck_kodi_pack_plan]] for the rest of what the Deck answered.
