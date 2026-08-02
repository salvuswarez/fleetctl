---
name: Operation Ids Need a Sequence, Not a Timestamp
description: Op ids built from int(time.time()) collided on rerun within the same second, silently replacing the record being rerun from.
type: project
---

`OperationRegistry.new_id()` appends a per-registry sequence number under the
registry's own lock. Before that, ids were `actor-step-<unix seconds>`, so
rerunning a step within one second minted an id that already existed and
overwrote the operation it was rerun from — the failed attempt's logs, the
evidence for why it was rerun, vanished.

**Why:** found by a test asserting the original survives its rerun, not in
review. Two runs of the same step on the same device inside one second is
exactly what a rerun button produces.

**How to apply:** mint operation ids through `registry.new_id(prefix)`, never
by formatting a timestamp at the call site.
