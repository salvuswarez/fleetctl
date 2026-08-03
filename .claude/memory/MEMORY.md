## Architecture Decisions

- [Three rings, twelve decisions](architecture_rings_and_decisions.md) — core/packs/apps, and the D1–D12 record behind them
- [New repo, not a refactor](architecture_new_repo_not_refactor.md) — S0–S6 done (2026-08-02); firestick_manager stays running until S7 cutover
- [HA panel parity is the cutover gate](project_ha_panel_parity.md) — 21 websocket commands; the audited mapping is `docs/ha-parity.md`

## Gotchas carried forward from `firestick_manager` (real hardware, verified)

- [adb_shell push() is broken](gotcha_adb_shell_push_broken.md) — zero bytes over a few MB; uploads go via netcat
- [toybox tar -z truncates](gotcha_toybox_tar_gzip_truncation.md) — split `tar` and `gzip`; Fire OS quirk, not Android
- [pm disable-user no-ops on Fire OS 5.x](gotcha_pm_disable_by_fireos_version.md) — silently; verify with `pm list packages -d`
- [ADB key identity mismatch](gotcha_adb_key_identity_mismatch.md) — CLI and HA hold separate keys; auth times out
- [Borrowed package lists are untrustworthy](gotcha_unverified_package_lists.md) — a prior list contained fabricated entries

## Gotchas discovered in fleetctl itself

- [str() on a Secret yields its mask](gotcha_secret_str_masks.md) — SMB auth fell back to guest; listings looked like an empty share
- [Operation ids need a sequence](gotcha_operation_id_collisions.md) — a rerun within one second used to overwrite the record it reran
- [ADB reauth after a reboot](gotcha_adb_reauth_after_reboot.md) — device unreachable right after a deploy; check for the on-screen prompt before assuming a bug

## Feedback

- [Gold device protection](feedback_gold_device_protection.md) — never experiment on the capture source; becomes enforced policy at S4

## Reference

- [Predecessor repo](reference_predecessor_firestick_manager.md) — where the ported behaviour comes from, and what not to copy
- [PAT in ha-cyberpunk remote](reference_ha_cyberpunk_pat_exposure.md) — credential found in a sibling repo's git config
