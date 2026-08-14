---
name: an SMB upload must publish by rename
description: writing straight to the artifact's real name left a 206MB fragment of a 350MB build that listed, sized and deployed exactly like a whole one.
type: project
---

`put()` wrote the payload directly to `builds/<name>.tar.gz`. A 350MB build
takes long enough that the router's SMB stack dropping the session mid-transfer
is routine, and when it did:

- **206,176,256 of 351,464,709 bytes** stayed on the share under the real name,
  with no sidecar — indistinguishable from a finished artifact.
- The retry restarted from byte zero and got **`STATUS_ACCESS_DENIED`
  (0xC0000022)** reopening that path, because the server still held the dead
  session's handle. Not a permissions fault: the directory is `drwxrwxrwx` and
  the share had 858GB free.

Uploads now stage to `<name>.tar.gz.uploading`, write the sidecar, then
`smbclient.replace()` into place. Three properties come out of that order:

- A visible payload is whole **and** already has its metadata beside it.
- A retry can `remove()` its own staging file, which is what makes a second
  attempt possible at all.
- `list()` skips `_UPLOADING`, so a fragment is never offered as deployable.

**Why:** the failure was silent and dangerous — a truncated build is offered
for deploy with no signal, and `deploy` would happily push it to a device.
Atomicity is the only thing that makes an interrupted transfer safe, and this
share interrupts transfers as a matter of course.

**How to apply:** any writer to this share publishes by rename. Do not raise
`_RETRIES` to compensate — see [[gotcha_smb_reads_need_explicit_share_access]]
for why more retries make this server worse, and
[[reference_kodi_shared_router_backend]] for what the share actually runs on.
