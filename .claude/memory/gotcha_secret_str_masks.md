---
name: str() on a Secret Yields Its Mask, Not Its Value
description: Coercing a resolved `!ref` with str() silently produced the mask; SMB authenticated as guest and every listing came back empty against a full share.
type: project
---

`Secret.__str__` returns the mask -- that is the whole point of the type. So
`str(data.get("user"))` in a settings loader turned a resolved
`!ref env:SMB_USER` into the mask string, which is non-empty and truthy, so
every "is it configured" check passed. SMB authenticated as guest, guest
cannot sign, and `list()` swallowed the error and returned `[]` against a
share holding 8 builds and 5 gold captures.

**Why:** the failure looks exactly like an empty share. Nothing raises, the
config reads correctly, and the password path was already right.

**How to apply:** any config field that may hold a `!ref` must be typed
`Secret | str` and unwrapped through one reveal helper at the edge. Never
`str()` a value that could be a Secret. See [[gotcha_operation_id_collisions]]
for the other silent-overwrite bug in this family.
