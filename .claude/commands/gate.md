Run the full quality gate and fix what it reports. No arguments.

1. `uv run black src tests` then `uv run isort src tests` — format in place.
2. `uv run mypy` — must report no issues; strict mode is not negotiable.
3. `uv run pytest --cov=src --cov-report=term-missing` — all green.
4. Fix anything that failed and re-run until clean. Report what changed.

This is exactly what CI runs (on Python 3.12 and 3.13). If the gate is green locally it should be green there.
