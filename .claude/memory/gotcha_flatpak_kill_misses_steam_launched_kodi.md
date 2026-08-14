---
name: pgrep -f matches the shell running it
description: `pgrep -f kodi.bin` counts the shell executing the command, so a stopped app reads as running; use the bracket trick or pgrep -x.
type: reference
---

`pgrep -f <pattern>` matches against full command lines, including the command
line of the shell that is running the `pgrep` itself. Over SSH,
`pgrep -c -f kodi.bin` returns at least 1 whether or not Kodi is running,
because `sh -c "pgrep -c -f kodi.bin"` contains the pattern.

Use a pattern that cannot match itself, or match the executable name exactly:

```bash
pgrep -c -f '[k]odi.bin'    # bracket trick
pgrep -c -x kodi.bin        # exact process name
ps -eo pid,comm,args | grep '[k]odi'
```

**Why:** it reads as a positive result, so it produces a false "still running"
rather than an obvious error. It led to a wrong conclusion that a config edit
had been made against a live Kodi and would be reverted on exit — neither was
true.

**How to apply:** never gate a decision on bare `pgrep -f`. This matters for
any step that must confirm an app is stopped before editing its config, since
Kodi rewrites `userdata/guisettings.xml` on exit and would genuinely clobber an
edit made while running. Also note `flatpak ps` lists only applications flatpak
is tracking, so it is not a reliable liveness check for an app launched from a
Steam shortcut — confirm with the process table.
