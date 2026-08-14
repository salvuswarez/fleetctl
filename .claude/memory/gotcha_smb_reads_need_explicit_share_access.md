---
name: SMB reads need explicit share_access
description: smbprotocol opens files exclusively by default, so concurrent sidecar reads collided and every artifact showed no metadata.
type: project
---

`smbclient.open_file()` defaults to **exclusive** access. A second reader of
the same path gets `STATUS_SHARING_VIOLATION` (`0xC0000043`). Listing an
artifact kind opens the directory and every `.meta.json` sidecar, and the HA
panel lists concurrently, so this fired constantly — every capture rendered
with `0 bytes` and no timestamp while the listing itself looked fine.

Reads pass `share_access="r"`. Writes stay exclusive, so a half-written
artifact is never readable as though complete.

Two things learned the hard way while fixing it:

- **The share is served by a small router-hosted SMB stack.** Raising
  `_RETRIES` to 4 with backoff turned contention into
  `STATUS_INSUFFICIENT_RESOURCES` — the server ran out of handles and
  *every* listing failed. Retries stay at 2. Contention is retried without
  `reset_connection_cache()`, which would not help and costs a reconnect.
- **Reproduce at the concurrency the log shows, not more.** Eight parallel
  listings exhausted the server and produced a failure mode that does not
  occur in practice; the HA log showed two workers.

`SMBOSError` carries a structured `.ntstatus`, so classify on that rather
than matching the message.

**Why:** the symptom was silent. `list()` swallowed a failed `listdir` into
an empty list, which is indistinguishable from a genuinely empty share — and
`latest()` then reports "no artifacts of kind" for a share that is full. That
path now warns unless the directory is simply absent.

**How to apply:** any new `open_file` for reading needs `share_access`. See
[[reference_kodi_shared_router_backend]].
