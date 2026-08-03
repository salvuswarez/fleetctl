<h1 style="margin: 0 0 8px 0; padding: 0; border: 0; font-size: 2em;">Configuration</h1>
<div style="color: #64748b; font-size: 15px; margin: 0 0 16px 0;">Every field in fleet.yml, .env, and devices.yml.</div>

<hr style="border: 0; border-top: 2px solid #005288; margin: 0 0 32px 0;"/>

<sub style="color: #64748b;">Last verified 2026-08-02</sub>

Three files, none required beyond `config/inventory/devices.yml` (and even that a first `scan` will create). Real values never get committed — see [Secrets and gitignore](#secrets-and-gitignore).

<br/>

<hr style="border: 0; border-top: 1px solid rgba(100, 116, 139, 0.35); margin: 24px 0;"/>

<br/>

<h2 style="border-left: 6px solid #005288; padding: 4px 0 10px 16px; margin: 40px 0 16px; border-bottom: 1px solid rgba(0, 82, 136, 0.25); background-image: url(data:image/svg+xml;utf8,%3Csvg%20xmlns%3D%27http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%27%20width%3D%27100%25%27%20height%3D%27100%25%27%3E%3Cdefs%3E%3Cpattern%20id%3D%27h%27%20width%3D%2720%27%20height%3D%2735%27%20patternUnits%3D%27userSpaceOnUse%27%3E%3Cpath%20d%3D%27M10%2023L0%2018V6L10%200l10%206v12L10%2023zm0%200v12%27%20fill%3D%27none%27%20stroke%3D%27%23005288%27%20stroke-opacity%3D%270.22%27%2F%3E%3C%2Fpattern%3E%3ClinearGradient%20id%3D%27lg%27%20x1%3D%270%25%27%20x2%3D%27100%25%27%3E%3Cstop%20offset%3D%270%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%271%27%2F%3E%3Cstop%20offset%3D%2785%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%270%27%2F%3E%3C%2FlinearGradient%3E%3Cmask%20id%3D%27f%27%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23lg%29%27%2F%3E%3C%2Fmask%3E%3C%2Fdefs%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23h%29%27%20mask%3D%27url%28%23f%29%27%2F%3E%3C%2Fsvg%3E); background-size: 100% 100%; background-repeat: no-repeat; border-radius: 3px;">`.env`</h2>

<div align="left" style="margin-bottom: -16px;"><img src="assets/lang-bash.svg" height="18"/></div>

```bash
cp .env.example .env
```

<div align="left" style="margin-bottom: -16px;"><img src="assets/lang-bash.svg" height="18"/></div>

```bash
SMB_HOST=nas.example.lan
SMB_SHARE=media
SMB_USER=fleetctl
SMB_PASS=change-me
SMB_BACKUP_DIR=firestick_backups
```

Loaded once, at container bootstrap, from the directory above `--config-dir` (the repo root by default). Only fills variables not already set in the real environment — a shell export or a container's own env wins over the file. `SMB_BACKUP_DIR` isn't read directly; it's there so `fleet.yml`'s `artifacts.smb.root` can reference it by naming the same value. These are the predecessor project's own variable names, kept on purpose so an existing `.env` can be copied over unchanged.

<br/>

<hr style="border: 0; border-top: 1px solid rgba(100, 116, 139, 0.35); margin: 24px 0;"/>

<br/>

<h2 style="border-left: 6px solid #005288; padding: 4px 0 10px 16px; margin: 40px 0 16px; border-bottom: 1px solid rgba(0, 82, 136, 0.25); background-image: url(data:image/svg+xml;utf8,%3Csvg%20xmlns%3D%27http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%27%20width%3D%27100%25%27%20height%3D%27100%25%27%3E%3Cdefs%3E%3Cpattern%20id%3D%27h%27%20width%3D%2720%27%20height%3D%2735%27%20patternUnits%3D%27userSpaceOnUse%27%3E%3Cpath%20d%3D%27M10%2023L0%2018V6L10%200l10%206v12L10%2023zm0%200v12%27%20fill%3D%27none%27%20stroke%3D%27%23005288%27%20stroke-opacity%3D%270.22%27%2F%3E%3C%2Fpattern%3E%3ClinearGradient%20id%3D%27lg%27%20x1%3D%270%25%27%20x2%3D%27100%25%27%3E%3Cstop%20offset%3D%270%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%271%27%2F%3E%3Cstop%20offset%3D%2785%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%270%27%2F%3E%3C%2FlinearGradient%3E%3Cmask%20id%3D%27f%27%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23lg%29%27%2F%3E%3C%2Fmask%3E%3C%2Fdefs%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23h%29%27%20mask%3D%27url%28%23f%29%27%2F%3E%3C%2Fsvg%3E); background-size: 100% 100%; background-repeat: no-repeat; border-radius: 3px;">`config/fleet.yml`</h2>

<div align="left" style="margin-bottom: -16px;"><img src="assets/lang-bash.svg" height="18"/></div>

```bash
cp config/fleet.yml.example config/fleet.yml
```

Every top-level block is optional. An empty file (or a missing one) is a fully permissive, local-storage, unaudited-beyond-defaults fleet.

<div style="margin-top: 52px; margin-left: 10px; color: #7986cb; font-size: 10.5px; font-weight: 700; letter-spacing: 2px; line-height: 1;">&#9642; REFERENCE &middot; fleet.yml Field</div>
<h3 style="margin-top: 4px; margin-left: 10px;">`artifacts.smb`</h3>

<div align="left" style="margin-bottom: -16px;"><img src="assets/lang-yaml.svg" height="18"/></div>

```yaml
artifacts:
  smb:
    host: 192.168.1.50
    share: Kodi
    root: fleetctl
    user: !ref env:SMB_USER
    password: !ref env:SMB_PASS
```

`!ref env:NAME` resolves against the process environment (see `.env` above) at load time — the value is wrapped in a `Secret` afterward and never appears in a log line, `repr()`, or diagnostic output. Drop the whole `smb:` block to store captures and builds under `~/.fleetctl/artifacts` instead; nothing else needs to change, since every step reads from `ArtifactStore` and doesn't know which backend it got.

`root` is a path *inside* the share — the predecessor's real deployment points it at a nested `kodi-wan/ha_storage/backups`-style path, so a share used for other things is untouched outside that subtree.

<div style="margin-top: 52px; margin-left: 10px; color: #7986cb; font-size: 10.5px; font-weight: 700; letter-spacing: 2px; line-height: 1;">&#9642; REFERENCE &middot; fleet.yml Field</div>
<h3 style="margin-top: 4px; margin-left: 10px;">`observability`</h3>

<div align="left" style="margin-bottom: -16px;"><img src="assets/lang-yaml.svg" height="18"/></div>

```yaml
observability:
  audit_dir: audit
```

Relative paths resolve under `--home` (`~/.fleetctl` by default), not the working directory. See [`observability.md`](observability.md) for what lands in diagnostics vs. the operation timeline vs. the audit chain, and why they're three separate streams.

<div style="margin-top: 52px; margin-left: 10px; color: #7986cb; font-size: 10.5px; font-weight: 700; letter-spacing: 2px; line-height: 1;">&#9642; REFERENCE &middot; fleet.yml Field</div>
<h3 style="margin-top: 4px; margin-left: 10px;">`policy`</h3>

<div align="left" style="margin-bottom: -16px;"><img src="assets/lang-yaml.svg" height="18"/></div>

```yaml
policy:
  actors:
    "cli:*":
      allow: ["*"]
      confirm: [destructive]
    "mcp:*":
      allow: ["*"]
      confirm: [mutating, destructive]
      max_devices: 3

  protected:
    - tags: [gold]
      deny: [kodi.deploy]
      reason: Prove a change on a spare device first.
```

Absent entirely → permissive: every actor may run every step, nothing needs approval.

**`actors`** — a list keyed by an actor glob (`cli:*`, `mcp:*`, `ha:*`, or an exact string). First match wins. Each entry may set:

| Field | Meaning |
|---|---|
| `allow` | Step id patterns this actor may invoke at all. Defaults to `["*"]`. |
| `deny` | Step id patterns refused outright — a policy denial, not answerable by `--approve`. |
| `confirm` | Effect classes (`mutating`, `destructive`) needing `--approve` before they run. |
| `max_devices` | Blast-radius cap for one workflow run; `0` means unlimited. |

**`protected`** — device protections checked before any actor rule, regardless of who's calling:

| Field | Meaning |
|---|---|
| `tags` | Every tag a device must carry to match (all of them, not any). |
| `ids` | Explicit device ids this rule covers, as an alternative to tags. |
| `deny` | Step id patterns denied on a matching device. `*` denies everything. |
| `reason` | Shown when this rule blocks something. |

A `mutating`/`destructive` step's effect is what `confirm:` and `deny:` key off — see `fleetctl steps` for every step's declared effect, and [`safety.md`](safety.md) for how a `confirm` verdict is satisfied on the CLI (`--approve`) versus through the agent toolkit (raises `ApprovalRequired`, which a caller must catch and re-call).

<br/>

<hr style="border: 0; border-top: 1px solid rgba(100, 116, 139, 0.35); margin: 24px 0;"/>

<br/>

<h2 style="border-left: 6px solid #005288; padding: 4px 0 10px 16px; margin: 40px 0 16px; border-bottom: 1px solid rgba(0, 82, 136, 0.25); background-image: url(data:image/svg+xml;utf8,%3Csvg%20xmlns%3D%27http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%27%20width%3D%27100%25%27%20height%3D%27100%25%27%3E%3Cdefs%3E%3Cpattern%20id%3D%27h%27%20width%3D%2720%27%20height%3D%2735%27%20patternUnits%3D%27userSpaceOnUse%27%3E%3Cpath%20d%3D%27M10%2023L0%2018V6L10%200l10%206v12L10%2023zm0%200v12%27%20fill%3D%27none%27%20stroke%3D%27%23005288%27%20stroke-opacity%3D%270.22%27%2F%3E%3C%2Fpattern%3E%3ClinearGradient%20id%3D%27lg%27%20x1%3D%270%25%27%20x2%3D%27100%25%27%3E%3Cstop%20offset%3D%270%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%271%27%2F%3E%3Cstop%20offset%3D%2785%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%270%27%2F%3E%3C%2FlinearGradient%3E%3Cmask%20id%3D%27f%27%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23lg%29%27%2F%3E%3C%2Fmask%3E%3C%2Fdefs%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23h%29%27%20mask%3D%27url%28%23f%29%27%2F%3E%3C%2Fsvg%3E); background-size: 100% 100%; background-repeat: no-repeat; border-radius: 3px;">`config/inventory/devices.yml`</h2>

Not something you write by hand from scratch — `fleetctl scan SUBNET` creates and updates it. Hand-edit `tags`, `name`, and `vars`; a scan never touches those three, only the fields it can actually observe (address, mac, model, os_version, status).

<div align="left" style="margin-bottom: -16px;"><img src="assets/lang-yaml.svg" height="18"/></div>

```yaml
devices:
  - id: living-room-stick
    type: firetv
    address: 192.168.1.50
    mac: aa:bb:cc:dd:ee:ff
    name: Living Room
    model: AFTKA
    os_version: "9"
    status: ok
    tags: [kodi, gold]
    vars:
      kodi:
        display:
          resolution_index: 18
          overscan: {left: 0, top: 0, right: 1920, bottom: 1080}
        settings:
          guisettings.xml:
            audiooutput.channels: "1"
```

<div style="margin-top: 52px; margin-left: 10px; color: #7986cb; font-size: 10.5px; font-weight: 700; letter-spacing: 2px; line-height: 1;">&#9642; REFERENCE &middot; devices.yml Field</div>
<h3 style="margin-top: 4px; margin-left: 10px;">`tags`</h3>

Plain strings, matched by workflow targets (`targets: {tags: [kodi]}`) and policy `protected` rules. Every shipped Kodi workflow targets the `kodi` tag; `kodi-capture-gold` targets `gold`. A device with neither tag is invisible to those workflows — this is the most common reason a workflow's plan comes back with zero tasks.

<div style="margin-top: 52px; margin-left: 10px; color: #7986cb; font-size: 10.5px; font-weight: 700; letter-spacing: 2px; line-height: 1;">&#9642; REFERENCE &middot; devices.yml Field</div>
<h3 style="margin-top: 4px; margin-left: 10px;">`status`</h3>

One of `ok`, `unauthorized`, or a handful of others a scan can set. Only a device with an actionable status can be targeted by `run` or a workflow; `unauthorized` means the device answered a scan but refused the ADB key — approve the on-device prompt and scan again.

<div style="margin-top: 52px; margin-left: 10px; color: #7986cb; font-size: 10.5px; font-weight: 700; letter-spacing: 2px; line-height: 1;">&#9642; REFERENCE &middot; devices.yml Field</div>
<h3 style="margin-top: 4px; margin-left: 10px;" id="device-vars">`vars`</h3>

Per-device config, merged as the highest layer below CLI `--set` overrides (see `for_device` in `core/config/layering.py` and [`cli-reference.md`](cli-reference.md#run)). For the shipped `kodi` app pack:

- **`vars.kodi.display`** — `resolution_index` and `overscan` (`left`/`top`/`right`/`bottom`), reapplied by `kodi.apply_device_config` after every deploy, since the shared build would otherwise overwrite a device's own calibration.
- **`vars.kodi.settings`** — userdata-relative setting overrides, keyed by the XML file they land in (e.g. `guisettings.xml`), also reapplied by `kodi.apply_device_config`.

A value here can be tried once without editing the file, via `--set kodi.display.resolution_index=18` on `fleetctl run` — see [`cli-reference.md`](cli-reference.md#run) for how dotted `--set` keys nest.

<br/>

<hr style="border: 0; border-top: 1px solid rgba(100, 116, 139, 0.35); margin: 24px 0;"/>

<br/>

<h2 style="border-left: 6px solid #005288; padding: 4px 0 10px 16px; margin: 40px 0 16px; border-bottom: 1px solid rgba(0, 82, 136, 0.25); background-image: url(data:image/svg+xml;utf8,%3Csvg%20xmlns%3D%27http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%27%20width%3D%27100%25%27%20height%3D%27100%25%27%3E%3Cdefs%3E%3Cpattern%20id%3D%27h%27%20width%3D%2720%27%20height%3D%2735%27%20patternUnits%3D%27userSpaceOnUse%27%3E%3Cpath%20d%3D%27M10%2023L0%2018V6L10%200l10%206v12L10%2023zm0%200v12%27%20fill%3D%27none%27%20stroke%3D%27%23005288%27%20stroke-opacity%3D%270.22%27%2F%3E%3C%2Fpattern%3E%3ClinearGradient%20id%3D%27lg%27%20x1%3D%270%25%27%20x2%3D%27100%25%27%3E%3Cstop%20offset%3D%270%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%271%27%2F%3E%3Cstop%20offset%3D%2785%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%270%27%2F%3E%3C%2FlinearGradient%3E%3Cmask%20id%3D%27f%27%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23lg%29%27%2F%3E%3C%2Fmask%3E%3C%2Fdefs%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23h%29%27%20mask%3D%27url%28%23f%29%27%2F%3E%3C%2Fsvg%3E); background-size: 100% 100%; background-repeat: no-repeat; border-radius: 3px;">Secrets and gitignore</h2>

`.env`, `config/fleet.yml`, and `config/inventory/devices.yml` are all gitignored; the three `.example` files are the tracked reference and must stay in sync with the real schema (checked by `tests/core/test_smb_store.py` and friends, and by this doc's own provenance date). Never copy a real IP, MAC, or credential out of a real config file into a doc, example, or comment — see the project `CLAUDE.md` for the full rule and the incident that established it.

<br/><br/>

<hr style="border: 0; border-top: 1px solid rgba(100, 116, 139, 0.35); margin: 24px 0;"/>

<br/>

<table>
<tr>
<td width="22%" valign="top" align="center">

<br/>
<strong>fleetctl</strong>
<br/><br/>
<sub>Configuration</sub>

</td>
<td width="26%" valign="top">

<h4><ins style="color: #2a8b93; text-decoration: none;">Documentation</ins></h4>

- [Getting Started](getting-started.md)
- [CLI Reference](cli-reference.md)
- [Configuration](configuration.md)
- [Architecture](architecture.md)
- [Safety & Policy](safety.md)

</td>
<td width="26%" valign="top">

<h4><ins style="color: #2a8b93; text-decoration: none;">Repositories</ins></h4>

- [fleetctl](https://github.com/salvuswarez/fleetctl)
- [firestick_manager](https://github.com/salvuswarez/firestick_manager) &mdash; predecessor
- [ha-cyberpunk](https://github.com/salvuswarez/ha-cyberpunk) &mdash; S7 consumer

<h4><ins style="color: #2a8b93; text-decoration: none;">References</ins></h4>

- [Observability](observability.md) &mdash; diagnostics, timeline, audit
- [Roadmap](roadmap.md) &mdash; S0&ndash;S8 stages
- [HA Parity](ha-parity.md) &mdash; panel command mapping

</td>
<td width="26%" valign="top">

<h4><ins style="color: #2a8b93; text-decoration: none;">About</ins></h4>

- Plugin-based home device fleet manager
- MIT licensed

<h4><ins style="color: #2a8b93; text-decoration: none;">Status</ins></h4>

- S0&ndash;S6 done &middot; S7 (HA cutover) not started

</td>
</tr>
</table>

<br/>

<hr style="border: 0; border-top: 1px solid rgba(100, 116, 139, 0.35); margin: 24px 0;"/>

<div align="center">
  <sub>fleetctl</sub>
</div>
