<h1 style="margin: 0 0 8px 0; padding: 0; border: 0; font-size: 2em;">Documentation Index</h1>
<div style="color: #64748b; font-size: 15px; margin: 0 0 16px 0;">Where to read next, and what's actually real today.</div>

<hr style="border: 0; border-top: 2px solid #005288; margin: 0 0 32px 0;"/>

<sub style="color: #64748b;">Last verified 2026-08-02</sub>

`fleetctl` is a plugin-based fleet manager for home devices, built in stages. This directory is the reader-facing documentation set; `docs/architecture.md` is the design source of truth and everything else here links into it rather than repeating it.

<blockquote style="border-left: 4px solid #7ab9d5; background-color: rgba(122, 185, 213, 0.08); padding: 14px 18px; margin: 16px 0; border-radius: 10px;">

**Status:** S0–S6 are complete — transport, packs, apps, config, workflows, policy, audit, and MCP all exist and have run against real hardware. S7 (Home Assistant cutover) and S8 (later stages) have not started. Every doc below says explicitly what's real today versus what's planned.

</blockquote>

<h2 style="border-left: 6px solid #005288; padding: 4px 0 10px 16px; margin: 40px 0 16px; border-bottom: 1px solid rgba(0, 82, 136, 0.25); background-image: url(data:image/svg+xml;utf8,%3Csvg%20xmlns%3D%27http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%27%20width%3D%27100%25%27%20height%3D%27100%25%27%3E%3Cdefs%3E%3Cpattern%20id%3D%27h%27%20width%3D%2720%27%20height%3D%2735%27%20patternUnits%3D%27userSpaceOnUse%27%3E%3Cpath%20d%3D%27M10%2023L0%2018V6L10%200l10%206v12L10%2023zm0%200v12%27%20fill%3D%27none%27%20stroke%3D%27%23005288%27%20stroke-opacity%3D%270.22%27%2F%3E%3C%2Fpattern%3E%3ClinearGradient%20id%3D%27lg%27%20x1%3D%270%25%27%20x2%3D%27100%25%27%3E%3Cstop%20offset%3D%270%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%271%27%2F%3E%3Cstop%20offset%3D%2785%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%270%27%2F%3E%3C%2FlinearGradient%3E%3Cmask%20id%3D%27f%27%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23lg%29%27%2F%3E%3C%2Fmask%3E%3C%2Fdefs%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23h%29%27%20mask%3D%27url%28%23f%29%27%2F%3E%3C%2Fsvg%3E); background-size: 100% 100%; background-repeat: no-repeat; border-radius: 3px;">The Documents</h2>

| Doc | For | What it covers |
|---|---|---|
| [`getting-started.md`](getting-started.md) | A new contributor cloning the repo today | Install, first-run config, scan a subnet, plan and run a workflow |
| [`cli-reference.md`](cli-reference.md) | Anyone running a command | Every subcommand and flag, generated from the CLI's own `--help` |
| [`configuration.md`](configuration.md) | Anyone writing `fleet.yml`, `.env`, or `devices.yml` | Every field in all three, with defaults and what each one gates |
| [`architecture.md`](architecture.md) | Anyone who wants the full design rationale | 15 sections, 21 diagrams: friction points in the predecessor, the three-ring target, config-as-code, workflows, observability, policy, MCP, the build plan, and every locked decision (§15) |
| [`pack-authoring.md`](pack-authoring.md) | Anyone writing a device pack or app pack | The extension contract: probes, capability declarations, effect classes, composition over inheritance |
| [`safety.md`](safety.md) | Anyone who will point this at real hardware | Effect classes, protected devices, per-actor policy, plan-then-run, `--approve`, blast-radius caps — cross-referenced against [`../SECURITY.md`](../SECURITY.md) |
| [`observability.md`](observability.md) | Anyone debugging a run or auditing what happened | The three separate streams (diagnostics, timeline, audit), why they're separate, and how correlation ids tie them together |
| [`roadmap.md`](roadmap.md) | Anyone deciding what to build next | Stages S0–S8, exit criteria, current status, and the sequencing rules that are hard to walk back |
| [`ha-parity.md`](ha-parity.md) | Anyone working on the Home Assistant cutover | All 21 panel commands mapped to their fleetctl equivalent, plus the behavioural differences the integration has to account for |

<h2 style="border-left: 6px solid #005288; padding: 4px 0 10px 16px; margin: 40px 0 16px; border-bottom: 1px solid rgba(0, 82, 136, 0.25); background-image: url(data:image/svg+xml;utf8,%3Csvg%20xmlns%3D%27http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%27%20width%3D%27100%25%27%20height%3D%27100%25%27%3E%3Cdefs%3E%3Cpattern%20id%3D%27h%27%20width%3D%2720%27%20height%3D%2735%27%20patternUnits%3D%27userSpaceOnUse%27%3E%3Cpath%20d%3D%27M10%2023L0%2018V6L10%200l10%206v12L10%2023zm0%200v12%27%20fill%3D%27none%27%20stroke%3D%27%23005288%27%20stroke-opacity%3D%270.22%27%2F%3E%3C%2Fpattern%3E%3ClinearGradient%20id%3D%27lg%27%20x1%3D%270%25%27%20x2%3D%27100%25%27%3E%3Cstop%20offset%3D%270%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%271%27%2F%3E%3Cstop%20offset%3D%2785%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%270%27%2F%3E%3C%2FlinearGradient%3E%3Cmask%20id%3D%27f%27%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23lg%29%27%2F%3E%3C%2Fmask%3E%3C%2Fdefs%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23h%29%27%20mask%3D%27url%28%23f%29%27%2F%3E%3C%2Fsvg%3E); background-size: 100% 100%; background-repeat: no-repeat; border-radius: 3px;">What Works Today vs. What's Planned</h2>

This table is the single fastest way to check whether something you're reading about actually exists yet. It mirrors `docs/architecture.md` §14 and `.claude/skills/build-stages/SKILL.md`, which is the canonical version — check there if this table and the code ever disagree.

| Stage | Contents | Status |
|---|---|---|
| **S0** | Repo bootstrap: `pyproject.toml`, `src/fleetctl/` skeleton, CI, licence | Done |
| **S1** | Core kernel: `Transport` protocol + `AdbTransport`, `ArtifactStore` (SMB + local), inventory, operations, secrets, observability | Done |
| **S2** | First pack (`packs/firetv`) + first app (`apps/kodi`), capture → build → deploy parity with `firestick_manager` | Done |
| **S3** | Config-as-code, layered resolution, workflow engine, plan/dry-run | Done |
| **S4** | Policy engine, effect classification enforcement, protected devices, audit hash chain | Done |
| **S5** | Shield Pro pack — validates the ring seams | Done |
| **S6** | MCP adapter (stdio) | Done |
| **S7** | Home Assistant cutover from `firestick_manager` | Not started |
| **S8** | `linux_host` + SSH transport, HTTP API if a consumer appears, `fleet.lock` | Not started |

Concretely, as of this writing: 108 source modules, 500 tests at ~90.6% coverage, mypy strict-clean. `fleetctl scan`, `run`, and `workflow run` have all executed against real Fire TV hardware, with artifacts on a real SMB share.

<h2 style="border-left: 6px solid #005288; padding: 4px 0 10px 16px; margin: 40px 0 16px; border-bottom: 1px solid rgba(0, 82, 136, 0.25); background-image: url(data:image/svg+xml;utf8,%3Csvg%20xmlns%3D%27http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%27%20width%3D%27100%25%27%20height%3D%27100%25%27%3E%3Cdefs%3E%3Cpattern%20id%3D%27h%27%20width%3D%2720%27%20height%3D%2735%27%20patternUnits%3D%27userSpaceOnUse%27%3E%3Cpath%20d%3D%27M10%2023L0%2018V6L10%200l10%206v12L10%2023zm0%200v12%27%20fill%3D%27none%27%20stroke%3D%27%23005288%27%20stroke-opacity%3D%270.22%27%2F%3E%3C%2Fpattern%3E%3ClinearGradient%20id%3D%27lg%27%20x1%3D%270%25%27%20x2%3D%27100%25%27%3E%3Cstop%20offset%3D%270%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%271%27%2F%3E%3Cstop%20offset%3D%2785%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%270%27%2F%3E%3C%2FlinearGradient%3E%3Cmask%20id%3D%27f%27%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23lg%29%27%2F%3E%3C%2Fmask%3E%3C%2Fdefs%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23h%29%27%20mask%3D%27url%28%23f%29%27%2F%3E%3C%2Fsvg%3E); background-size: 100% 100%; background-repeat: no-repeat; border-radius: 3px;">Where to Read Next</h2>

- New to the repo and want to run something → [`getting-started.md`](getting-started.md)
- Looking up a specific command or flag → [`cli-reference.md`](cli-reference.md)
- Writing or editing `fleet.yml`, `.env`, or `devices.yml` → [`configuration.md`](configuration.md)
- Want the full design before writing any code → [`architecture.md`](architecture.md)
- Planning to add a device type or an app → [`pack-authoring.md`](pack-authoring.md)
- Concerned about what this tool can do to real hardware → [`safety.md`](safety.md) and [`../SECURITY.md`](../SECURITY.md)
- Wondering what's next or why the stages are ordered the way they are → [`roadmap.md`](roadmap.md)
- Working on the Home Assistant integration → [`ha-parity.md`](ha-parity.md)

<br/><br/>

<hr style="border: 0; border-top: 1px solid rgba(100, 116, 139, 0.35); margin: 24px 0;"/>

<br/>

<table>
<tr>
<td width="22%" valign="top" align="center">

<br/>
<strong>fleetctl</strong>
<br/><br/>
<sub>Documentation Index</sub>

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
