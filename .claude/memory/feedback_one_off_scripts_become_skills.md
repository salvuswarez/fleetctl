---
name: promote one-off device scripts into skills
description: Throwaway scripts written to drive fleetctl against live hardware should be captured as a skill, not left in .claude/temp/ to be rewritten next session.
type: feedback
---

When a script is written to drive `fleetctl` against real hardware — a probe,
a capture, an artifact inspection, a build — it must be promoted into a skill
(project-local `.claude/skills/` here, or user-global `~/.claude/skills/` when
it is not repo-specific) rather than left in `.claude/temp/`.

Raised 2026-08-06 after four such scripts (`deck_probe.py`,
`deck_capture.py`, `inspect_gold_build.py`, `build_deck.py`) accumulated in
`.claude/temp/` during the Steam Deck work. Captured as
`.claude/skills/live-device-runs/SKILL.md`.

**Why:** these scripts encode real, hard-won knowledge — how to build a step
context by hand when the checkout has no `config/`, how to reach the SMB store
from `.env`, how to verify an archive before trusting it. Left as temp files
they are deleted by the next cleanup and rewritten from scratch, and each
rewrite re-derives the same details and risks re-making the same mistakes.

**How to apply:** when a temp script proves useful more than once, or encodes
a non-obvious setup, write it into a skill in the same session — do not wait
to be asked. Keep the credential handling in the skill as a *pattern*
(`.env` + `load_dotenv` + never echo), never a value.
