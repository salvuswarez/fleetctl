---
name: a quoted ~ path silently does nothing
description: shlex.quote stops the remote shell expanding `~`, so commands act on a literal `~` directory, succeed, and change nothing.
type: project
---

Every remote command quotes its arguments, which is right — an unquoted path
with a space deletes two directories. But quoting also stops the remote shell
expanding `~`:

```python
runner.exec_ok(f"rm -rf {shlex.quote('~/.cache/fleetctl')}")   # rm -rf '~/.cache/fleetctl'
```

That targets a literal `~` directory, which does not exist. `rm -rf` on a
missing path exits 0, so the step reports success and deletes nothing. The same
bite hit `df -k '~/...'` in `steamdeck.check` earlier.

`packs/posix/actions.expand_home()` resolves it via `echo $HOME` and raises
when the home directory cannot be read, rather than acting on a path that is
still wrong. `remove_paths` and `PosixStateManager` both go through it.

**Why:** it is invisible to `FakeTransport` — the scripted double does not care
whether a path is literal — so unit tests pass while the device is untouched.
It only shows up as "the step said it worked and nothing changed".

**How to apply:** any `~`-relative value from a data file must be expanded
before it reaches a quoted command. Assert on the *expanded* path in tests
(`rm -rf /home/deck/...`, never `rm -rf '~/...'`), and verify space-reclaiming
work against hardware — a no-op deletion looks identical to a successful one.
See [[gotcha_stripped_settings_must_be_creatable_on_reapply]].
