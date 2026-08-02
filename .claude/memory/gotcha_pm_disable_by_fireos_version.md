---
name: pm disable-user silently no-ops on Fire OS 5.x
description: On 1st-gen stick hardware many system packages cannot be disabled from a non-root ADB shell, and the command fails without a useful error. Verify with `pm list packages -d`.
type: project
---

`pm disable-user --user 0 <package>` is blocked for many system packages from a non-root shell on **Fire OS 5.x** (1st-generation stick hardware) — it fails with a `SecurityException` or simply no-ops, without surfacing a usable error to the caller. It works normally on Fire OS 7.x.

**Why:** Discovered in the predecessor project when a maintenance run reported success across the fleet but the older devices were unchanged. A debloat step that logs "disabled 90 packages" and verifies nothing is worse than no debloat, because it hides the failure.

**How to apply:** Never report a debloat as successful without verifying via `pm list packages -d`. The per-package outcome belongs in the audit stream (each `pm disable-user` is a `DESTRUCTIVE` effect with its own record), not collapsed into one summary log line — that collapse is exactly what made this undiagnosable in the predecessor. Gate behaviour on the device's Fire OS version, held as pack data. See [[gotcha_unverified_package_lists]].
