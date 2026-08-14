---
name: gotcha_shield_seam_git_test_passes_vacuously
description: test_git_shows_no_core_or_kodi_changes_in_the_shield_commit runs git from src/ instead of the repo root, so it has never checked anything.
metadata:
  type: project
---

`tests/unit/packs/test_shield_seam.py::test_git_shows_no_core_or_kodi_changes_in_the_shield_commit`
computes its repo root as `Path(kodi_steps.__file__).resolve().parents[3]`.
That is `src/`, not the repo root — `steps.py` is four levels deep
(`src/fleetctl/apps/kodi/`), so it needs `parents[4]`.

Run from `src/`, the pathspecs `src/fleetctl/core` and `src/fleetctl/apps`
match nothing. `git status --porcelain` exits **0** with empty output for an
unmatched pathspec (unlike `git add`), so the `returncode != 0` skip never
fires and the assertion compares `"" == ""`. **It passes vacuously and always
has.** Confirmed 2026-08-12: the suite was green with `steps.py` modified and
`abi.py` untracked.

**Why it matters:** this is the test carrying the S5 claim that adding a
device type touched nothing it should not have. That claim currently has no
evidence behind it. The real guarantee lives in its sibling
`test_adding_the_shield_required_no_change_in_the_kodi_app_pack`, which is
static and does work.

**How to apply:** do not cite this test as evidence of ring separation. Before
fixing the path, note that the assertion is also wrong in kind — it checks the
*working tree*, so once corrected it fails during any legitimate `core/` or
`apps/` edit, not just a bad one. A working-tree check cannot express "one
historical commit stayed in its lane"; prefer deleting it in favour of the
static sibling. Related: [[architecture_rings_and_decisions]].
