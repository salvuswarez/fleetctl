# Security

## Reporting a vulnerability

Report privately via GitHub's [security advisory
form](https://github.com/salvuswarez/fleetctl/security/advisories/new)
rather than opening a public issue. Expect an acknowledgement within a week.

## What this tool is

> [!CAUTION]
> `fleetctl` is a remote administration tool. By design it can wipe
> application profiles, disable system packages, install APKs, and reboot
> devices across a local network. Treat it accordingly.

## Threat model

**In scope:**

- Credential disclosure through logs, audit records, error messages, or
  committed configuration.
- Command injection via values that reach a device shell (device names,
  config values, inventory fields).
- Path traversal in artifact and backup references.
- Privilege escalation across the policy layer — an actor performing a step
  it was not authorized for.
- Tampering with the audit trail.

**Out of scope:**

- An attacker who already has the ADB private key or the host filesystem.
- Devices deliberately marked unmanaged.
- The security of Android Debug Bridge itself, which offers no transport
  encryption on a LAN.

## Standing risks you should understand

> [!WARNING]
> **The ADB private key is a standing credential.** Once a device authorizes
> it, the key grants shell access indefinitely with no expiry and no
> revocation short of re-pairing the device. It is stored at `0600` in a
> `0700` directory, outside the repository. Every use is recorded as an
> `AUTH` audit event so a leaked key's blast radius can be scoped.

**ADB traffic is unencrypted.** Anything `fleetctl` sends to a device —
including settings values — is visible to anyone on the same network
segment. Do not put secrets in device settings.

**Audit records default to the SMB share.** That location is reachable by
everything on the household network. Redaction is applied before write and
is not optional, and the log is hash-chained so tampering is detectable.
Set `observability.audit.destination: local` to keep it on the host.

## Practices this project holds itself to

- **Config holds references, never values.** Secrets resolve at the edge
  through a `SecretProvider`; a config file is safe to share.
- **Secrets are `SecretStr`.** They render as `**********` unless a caller
  deliberately unwraps them.
- **No real device data in the repository.** No real IPs, MAC addresses,
  hostnames, serials, or credentials — in code, docs, tests, or comments.
  Examples use `192.168.1.50` and `aa:bb:cc:dd:ee:ff`.
- **Values reaching a shell are validated, not escaped and hoped for.**
- **Destructive steps are declared as such** and gated by policy.
