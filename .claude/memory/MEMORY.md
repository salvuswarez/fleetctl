## Architecture Decisions

- [Three rings, twelve decisions](architecture_rings_and_decisions.md) — core/packs/apps, and the D1–D12 record behind them
- [New repo, not a refactor](architecture_new_repo_not_refactor.md) — S0–S6 done (2026-08-02); firestick_manager stays running until S7 cutover
- [HA panel parity is the cutover gate](project_ha_panel_parity.md) — 21 websocket commands; the audited mapping is `docs/ha-parity.md`
- [Steam Deck Kodi pack — hardware-verified](project_steamdeck_kodi_pack_plan.md) — SteamOS 3.8.24 quirks read off a real Deck; the Flatpak Kodi path is NOT `…/data/.kodi`

## Gotchas carried forward from `firestick_manager` (real hardware, verified)

- [adb_shell push() is broken](gotcha_adb_shell_push_broken.md) — zero bytes over a few MB; uploads go via netcat
- [toybox tar -z truncates](gotcha_toybox_tar_gzip_truncation.md) — split `tar` and `gzip`; Fire OS quirk, not Android
- [pm disable-user no-ops on Fire OS 5.x](gotcha_pm_disable_by_fireos_version.md) — silently; verify with `pm list packages -d`
- [ADB key identity mismatch](gotcha_adb_key_identity_mismatch.md) — CLI and HA hold separate keys; auth times out
- [Borrowed package lists are untrustworthy](gotcha_unverified_package_lists.md) — a prior list contained fabricated entries
- [Textures13.db survives a Thumbnails prune](gotcha_kodi_texture_index_survives_thumbnail_prune.md) — dangling texture index, a compounding OOM cause
- [Inventory IPs drift from DHCP reassignment](gotcha_inventory_ip_drift_from_dhcp.md) — verify live before trusting a stored IP
- [One box reports two MACs](gotcha_one_box_reports_two_macs.md) — ethernet vs wifi made the Shield two records; a serial outranks a changed MAC
- [Arctic Fuse caches compiled shortcut XML](gotcha_arctic_fuse_compiled_shortcut_cache.md) — a hub-layout deploy can look like a no-op until that cache is cleared and Kodi restarts

## Gotchas discovered in fleetctl itself

- [str() on a Secret yields its mask](gotcha_secret_str_masks.md) — SMB auth fell back to guest; listings looked like an empty share
- [Operation ids need a sequence](gotcha_operation_id_collisions.md) — a rerun within one second used to overwrite the record it reran
- [ADB reauth after a reboot](gotcha_adb_reauth_after_reboot.md) — device unreachable right after a deploy; check for the on-screen prompt before assuming a bug
- [Cheap reads must not be run_step](gotcha_reads_should_not_be_operations.md) — a polled read became an uncancellable RUNNING operation per page load
- [Dev commands never build a wheel](gotcha_wheel_build_never_tested.md) — v0.1.0 shipped uninstallable through a fully green gate
- [SteamOS ships no `hostname` binary](gotcha_steamos_ships_no_hostname_binary.md) — `exec_ok` swallowed the 127 and the fact vanished silently; use `uname -n`
- [`flatpak info --show-version` is unsupported](gotcha_flatpak_show_version_unsupported.md) — installed Kodi read as absent; parse the `Version:` line
- [A sleeping Deck answers ping but drops TCP](gotcha_steam_deck_wifi_powersave_drops_tcp.md) — refused vs timed-out means SSH-off vs asleep
- [A gold build carries the capture device's display config](gotcha_gold_build_carries_capture_device_display_config.md) — SIGFPE on a Deck; `apply_device_config` overlays but never neutralises
- [`pgrep -f` matches the shell running it](gotcha_flatpak_kill_misses_steam_launched_kodi.md) — a stopped app reads as running; use `[k]odi.bin` or `pgrep -x`
- [`default="true"` discards a setting override](gotcha_kodi_setting_default_attribute_discards_override.md) — reads back correctly, never takes effect; clear the attribute
- [Stripped settings must be creatable on reapply](gotcha_stripped_settings_must_be_creatable_on_reapply.md) — strip + reapply only compose if reapply can create; `apply_overscan` still has no caller
- [Nothing ships a whole file into a profile](gotcha_no_transform_ships_whole_files_into_a_profile.md) — closed by `ShipFiles`/`AddVideoSources`; layouts and profiles both support `extends:`
- [A quoted `~` path silently does nothing](gotcha_quoted_tilde_paths_silently_do_nothing.md) — `shlex.quote` blocks shell expansion; `rm -rf` succeeds and deletes nothing
- [A transport can't answer for a pack's capabilities](gotcha_transport_cannot_answer_for_pack_capabilities.md) — wire verbs vs derived; one SSH transport serves packs of differing capability
- [SMB reads need explicit `share_access`](gotcha_smb_reads_need_explicit_share_access.md) — exclusive by default; sidecars collided and artifacts showed no metadata
- [An Umbrella download blocks on a confirm dialog](gotcha_umbrella_download_waits_on_a_confirm_dialog.md) — declining leaves no file, no error, no log line
- [A download dies silently on an unresolved magnet](gotcha_umbrella_download_fails_silently_on_unresolved_magnet.md) — spinner then nothing; evidence is in `temp/umbrella.log`, not `kodi.log`
- [A shared MySQL library can't serve offline downloads](gotcha_shared_mysql_library_defeats_offline_downloads.md) — library needs network and is fleet-wide; device-local media belongs in `sources.xml` only
- [An entry-point app is constructed with no arguments](gotcha_entry_point_apps_cannot_be_parameterised.md) — every panel build silently used `gold`; per-run choices belong to the composition root
- [An SMB upload must publish by rename](gotcha_smb_upload_must_publish_by_rename.md) — a dropped session left a 206MB fragment of a 350MB build that looked complete and deployable
- [HA regenerates its own `fleet.yml`](gotcha_ha_regenerates_fleet_yml_every_setup.md) — a hand-added `protected:` rule dies on reload; protection hangs off inventory tags, and CLI vs HA resolve different policies
- [Live scripts must use bootstrap's key dir](gotcha_live_scripts_must_use_the_bootstrap_key_dir.md) — a script picking its own `key_dir` presents a second ADB identity, and the device prompt you accepted buys the CLI nothing
- [The shield seam's git test passes vacuously](gotcha_shield_seam_git_test_passes_vacuously.md) — wrong `parents[]` index runs git from `src/`; the S5 "touched nothing else" claim has no evidence behind it
- [A device `tar` rejects PAX long names](gotcha_device_tar_rejects_pax_long_names.md) — Python's default format aborts extraction mid-member; builds must be `GNU_FORMAT`
- [`AdbTransport.exec` cannot see an exit status](gotcha_adb_exec_cannot_see_exit_status.md) — a failed command reads as success; and `ls` error text is non-empty, so the obvious verification lies too
- [Android 11 `/sdcard` blocks `pm install`](gotcha_android_11_sdcard_blocks_pm_install.md) — FUSE mount `system_server` can't read; stage APKs in `/data/local/tmp`
- [Android TV cannot autostart Kodi](gotcha_android_tv_cannot_autostart_kodi.md) — no HOME activity, no `boot_to_app`; use an external trigger calling `kodi.launch`
- [Kodi 21 moved the cache out of advancedsettings](gotcha_kodi21_moved_cache_out_of_advancedsettings.md) — the old block is inert; the live value is `filecache.memorysize` in guisettings
- [The HOME launcher can't be set over ADB](gotcha_home_launcher_cannot_be_set_over_adb.md) — `set-home-activity` and RoleManager both print success and change nothing; needs on-device consent

## Feedback

- [Gold device protection](feedback_gold_device_protection.md) — never experiment on the capture source; becomes enforced policy at S4
- [Tests live under `tests/unit/`](feedback_tests_live_under_tests_unit.md) — nothing sits directly in `tests/`; watch `__file__`-relative paths
- [One-off device scripts become skills](feedback_one_off_scripts_become_skills.md) — captured as `.claude/skills/live-device-runs/`, not left in `.claude/temp/`
- [Comments state current what and why](feedback_comments_concise_no_history.md) — no dates, no "was X now Y"; history lives in git and memory

## Reference

- [Predecessor repo](reference_predecessor_firestick_manager.md) — retired 2026-08-06; where the ported behaviour came from, and what was left behind on purpose
- [Kodi's shared router backend](reference_kodi_shared_router_backend.md) — MariaDB/Entware + SMB infra outside this repo, and a real outage's diagnostic lessons
- [All Kodi navigation routes through TMDbHelper](reference_kodi_navigation_is_tmdbhelper_first.md) — menus come from player JSONs, not the skin or provider menus
- [PAT in ha-cyberpunk remote](reference_ha_cyberpunk_pat_exposure.md) — credential found in a sibling repo's git config
