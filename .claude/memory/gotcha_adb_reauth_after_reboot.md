---
name: A device reboot revokes ADB authorization mid-session
description: cody's 3rd Fire TV stopped answering fleetctl's ADB key right after a deploy, even though the deploy itself succeeded (confirmed visually on-device). Ping and port 5555 stayed up; only the handshake timed out.
type: project
---

After deploying to `cody-s-3rd-fire-tv` (192.168.50.232) on 2026-08-02, the device stopped answering ADB immediately afterward. Ping succeeded and port 5555 was open the whole time; only the ADB handshake itself timed out (`DeviceUnauthorizedError` / `TcpTimeoutException`). A sibling stick on the same key answered instantly, ruling out the key or the network generally.

**The deploy itself was confirmed successful** by checking the device/Kodi directly (2026-08-02) — the build landed and runs correctly. **fleetctl's own ADB access to this device did not recover during the same session**, even after the user reported checking the device. That means this is not simply "approve the prompt once and it's fine" — either the prompt needs approving again on that specific device, or something about this key/device pairing needs re-establishing beyond a single tap. Not yet root-caused.

**Why:** this matters because both `kodi-deploy-all` and `kodi-refresh` run `kodi.apply_device_config` immediately after `kodi.deploy` against the same device — if a deploy or reboot revokes ADB auth, the very next step in the same workflow run hits this wall. The deploy step itself apparently isn't blocked by it (it completed and worked), so the risk is specifically to whatever runs *after* deploy in the same session, and to any future fleetctl command against this device until access is restored.

**How to apply:** if a device goes unreachable right after a deploy with this exact signature (reachable, port open, handshake times out, deploy itself was otherwise fine), don't treat it as a fleetctl defect in the deploy path. Check whether `cody-s-3rd-fire-tv` (192.168.50.232) has re-authorized fleetctl's ADB key before running anything else against it — `.claude/temp/verify_deploy.py` (if still present) is the quickest recheck. If it's still unauthorized after an on-device approval, that's worth its own investigation (key mismatch? "always allow" not set? a second prompt re-appearing?) rather than assumed already understood.
