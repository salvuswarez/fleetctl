---
name: separate ADB key identities cause auth-handshake timeouts
description: The CLI and the Home Assistant integration hold different RSA key pairs. A device authorized for one is not authorized for the other, and the failure looks like a timeout rather than a permission error.
type: project
---

Each consumer keeps its own ADB key store — the CLI under the user's home directory, the Home Assistant integration under its config directory. A device that has authorized one key has **not** authorized the other, and the resulting failure presents as an auth-handshake timeout rather than an explicit permission error. Diagnosing it by symptom alone is slow.

**Why:** Bit the predecessor project during a capture run that worked from the CLI and failed from HA against the same device. The ADB private key is a standing authorization token with no expiry and no revocation short of re-pairing the device.

**How to apply:** When an authorization failure appears, first establish *which key store the failing consumer uses* before assuming the device is unreachable. Record every signer use as an `AUTH` audit event so a leaked key's blast radius can be scoped — that is the S1 observability requirement this gotcha motivates. Do not share one key across consumers to "fix" this; separate identities are correct, they just need to be visible.
