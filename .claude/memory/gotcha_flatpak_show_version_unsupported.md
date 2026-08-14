---
name: flatpak info --show-version is unsupported on SteamOS
description: The flag produces no output on SteamOS 3.8's Flatpak, so an installed app read as absent; parse the `Version:` line of plain `flatpak info` instead.
type: reference
---

`flatpak info --show-version <id>` produces **no output** on the Flatpak
shipped with SteamOS 3.8. Plain `flatpak info <id>` works and prints a
`Version:` line (`Version: 21.3-Omega` for `tv.kodi.Kodi`), as does
`flatpak list --app --columns=application,version`.

Because `FlatpakAppManager.installed_version` reads through `exec_ok`, which
returns `""` on failure by design, an installed Kodi reported as **not
installed**. Found on live hardware 2026-08-06 during the first Deck capture;
the unit suite was green because the fixture scripted `--show-version` from an
assumption.

Fixed by parsing the `Version:` line of `flatpak info`. Match on the key
exactly — `Ref:` and `Branch:` also carry the branch name and would otherwise
be mistaken for a version.

**Why:** the second instance of the same failure mode in one session, after
[[gotcha_steamos_ships_no_hostname_binary]]. `exec_ok` swallowing a failure is
right for an optional fact, but it makes "the command was wrong" and "the
answer is genuinely absent" indistinguishable — and a test double scripted
from an assumed CLI never catches it.

**How to apply:** when a probe reports something absent that you believe is
present, run the raw command over SSH before touching the parser. Prefer
parsing a command's normal output over relying on a convenience flag that may
not exist in every version. See [[project_steamdeck_kodi_pack_plan]].
