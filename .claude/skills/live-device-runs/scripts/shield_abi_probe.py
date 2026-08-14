"""Read-only probe: can a `gold` build's addon binaries run on this Shield?

Every command here is `Effect.READ`. Nothing is written, moved or deleted.

Answers four questions the unit suite structurally cannot:
  1. Does `ShieldPack.probe` claim the device off real `getprop` output?
  2. What ABI does the hardware run, and what ABI is the installed Kodi?
  3. Is `/sdcard/Android/data/<pkg>/files/.kodi` reachable from an adb shell
     on Android 11, where `Android/data` access was restricted?
  4. Does the Kodi profile actually contain what a capture would expect?

Usage:  uv run python .claude/skills/live-device-runs/scripts/shield_abi_probe.py <address>
"""

from __future__ import annotations

import sys
from pathlib import Path

from fleetctl.apps.kodi.spec import state_spec
from fleetctl.core.effects import Effect
from fleetctl.packs.android import actions
from fleetctl.packs.android.keys import AdbKeyStore
from fleetctl.packs.shield.pack import ShieldPack

# Must match what the composition root hands packs (`home / "keys"` in
# cli/bootstrap.py). A probe using its own directory presents a different key,
# and the device's on-screen authorization would not carry over to the CLI —
# the ADB key identity mismatch that cost the predecessor a debugging session.
KEY_DIR = Path.home() / ".fleetctl" / "keys"


def main(address: str) -> int:
    pack = ShieldPack()
    keys = AdbKeyStore(KEY_DIR)
    print(f"adb key fingerprint: {keys.fingerprint}")
    print(f"connecting to {address}:5555 (accept the on-screen prompt if it appears)...")

    transport = pack.transport_for(
        type("D", (), {"address": address, "id": "probe"})(),  # type: ignore[arg-type]
        {"key_dir": KEY_DIR, "audit": None},
    )

    try:
        claimed = pack.probe(transport)
        print(f"\n-- probe --\nclaimed: {claimed}")

        print("\n-- hardware ABI --")
        for prop in ("ro.product.cpu.abi", "ro.product.cpu.abilist", "ro.build.version.sdk"):
            print(f"{prop} = {transport.exec_ok(f'getprop {prop}', effect=Effect.READ).strip()!r}")

        package = state_spec().identifier_for("android")
        print(f"\n-- installed Kodi ({package}) --")
        print(f"versionName = {actions.installed_version(transport, package)!r}")
        dump = transport.exec_ok(f"dumpsys package {package}", effect=Effect.READ)
        for line in dump.splitlines():
            if "CpuAbi" in line or "codePath" in line or "legacyNativeLibraryDir" in line:
                print(line.strip())

        root = pack.state_root(transport, state_spec())
        print(f"\n-- profile root reachability --\nroot = {root}")
        for path in (root, f"{root}/addons", f"{root}/userdata"):
            listing = transport.exec_ok(f"ls {path} 2>&1", effect=Effect.READ).strip()
            head = listing.splitlines()[:4]
            print(f"ls {path} -> {head if head else '(empty or denied)'}")

        print("\n-- addon binaries present (ABI evidence) --")
        found = transport.exec_ok(f"ls {root}/addons 2>&1", effect=Effect.READ)
        binary_addons = [n for n in found.split() if n.startswith(("inputstream.", "pvr.", "script.module.py"))]
        print(f"binary-carrying addons: {binary_addons or '(none listed)'}")
        for addon in binary_addons[:3]:
            libs = transport.exec_ok(f"ls {root}/addons/{addon} 2>&1", effect=Effect.READ)
            print(f"  {addon}: {libs.split()[:6]}")
    finally:
        transport.close()
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
