---
name: tests live under tests/unit/
description: Every test file belongs under tests/unit/, not directly in tests/ — corrected 2026-08-06 during the S8 work.
type: feedback
---

All test files live under `tests/unit/` — `tests/unit/core/`, `tests/unit/packs/`,
`tests/unit/apps/`, plus the top-level ones (`test_architecture.py`, `test_cli.py`,
`conftest.py`). Nothing sits directly in `tests/`. The whole tree was moved there
on 2026-08-06; `pytest.ini_options` `testpaths = ["tests"]` still finds it.

**Why:** the user corrected the layout mid-task while `packs/posix` and
`packs/linux_host` tests were being added. It reserves `tests/` for future
sibling suites (integration, contract) rather than mixing levels in one
directory.

**How to apply:** put new test files under `tests/unit/<ring>/`. Anything that
computes a repo path from `__file__` needs one more `parents[]` level after the
move — `tests/unit/test_architecture.py` uses `parents[2]` to reach the repo
root, and getting this wrong makes the ring tests silently scan nothing. See
[[architecture_rings_and_decisions]] for what those tests enforce.
