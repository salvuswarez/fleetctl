"""Answer the two questions left before a Kodi deploy to the Shield.

1. What ABI is the *installed Kodi process*? A device that lists armeabi-v7a
   can run 32-bit processes, but a 64-bit Kodi cannot dlopen a 32-bit addon
   binary -- so the app's own ABI is what decides, not the device's abilist.
2. Is the Kodi state root reachable and writable from an adb shell? Android 11
   restricted /sdcard/Android/data; Fire OS 7 is Android 9, so this is
   untested territory for this pack.

Read-only. Every command is Effect.READ except one touch/rm pair, which is
the only way to answer (2) honestly.

Usage:  uv run python .claude/skills/live-device-runs/scripts/shield_deploy_readiness.py <device-id>

The device id is read from `config/inventory/devices.yml`, which is gitignored
-- pass yours on the command line rather than editing a default in here, so a
real device id never lands in this tracked directory.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fleetctl.apps.kodi.spec import state_spec
from fleetctl.core.effects import Effect
from fleetctl.core.inventory.store import DeviceStore
from fleetctl.packs.android.keys import AdbKeyStore
from fleetctl.packs.android.state import AndroidStateManager
from fleetctl.packs.android.transport import AdbTransport
from fleetctl.packs.shield.pack import ShieldPack

# Must match cli/bootstrap.py -- a different directory is a different ADB
# identity, and the device has authorized only the one the CLI presents.
KEY_DIR = Path.home() / ".fleetctl" / "keys"


def main(device_id: str) -> int:
    inventory = DeviceStore(Path("config") / "inventory" / "devices.yml")
    device = inventory.get(device_id)
    if device is None:
        print(f"No {device_id} in the inventory")
        return 1

    pack = ShieldPack()
    transport = AdbTransport(device.address, AdbKeyStore(KEY_DIR), use_netcat=pack.quirks.push_via_netcat)
    transport.connect()

    package = state_spec().identifier_for("android")
    root = AndroidStateManager(transport, pack.quirks).state_root(state_spec())

    print("== Kodi install ==")
    dump = transport.exec_ok(f"dumpsys package {package}", effect=Effect.READ)
    for line in dump.splitlines():
        stripped = line.strip()
        if stripped.startswith(("versionName=", "primaryCpuAbi=", "legacyNativeLibraryDir=", "codePath=")):
            print(f"  {stripped}")

    print("\n== State root ==")
    print(f"  path: {root}")
    print(f"  ls  : {transport.exec_ok(f'ls -d {root} 2>&1', effect=Effect.READ).strip() or '(no output)'}")
    print(f"  list: {transport.exec_ok(f'ls {root} 2>&1', effect=Effect.READ).strip() or '(empty)'}")

    print("\n== Writability (the Android 11 question) ==")
    # Never substring-match the path against `ls` output: the failure message
    # *contains* the path, so the probe reads as success when it failed.
    # Echo a sentinel only reachable if the command chain actually ran.
    probe = f"{root}/.fleetctl_write_probe"
    for label, target in (("/sdcard/Android/data", "/sdcard/Android/data/.fleetctl_probe"), ("kodi state root", probe)):
        parent = target.rsplit("/", 1)[0]
        out = transport.exec_ok(f"mkdir -p {parent} && touch {target} && echo FLEETCTL_OK || echo FLEETCTL_FAIL", effect=Effect.MUTATING).strip()
        verdict = "YES" if out.endswith("FLEETCTL_OK") else "NO"
        print(f"  {label:22} writable: {verdict:3}  ({out or 'no output'})")
        transport.exec_ok(f"rm -f {target}", effect=Effect.DESTRUCTIVE)

    print("\n== Native addon binaries already on the device ==")
    found = transport.exec_ok(f"find {root}/addons -name '*.so' 2>/dev/null | head -5", effect=Effect.READ).strip()
    print(f"  {found or '(none found)'}")

    transport.close()
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    sys.exit(main(sys.argv[1]))
