---
name: comments state current what and why, not history
description: Keep docstrings and comments descriptive but concise — explain what a thing does and why, never how it came to be.
type: feedback
---

Comments and docstrings say **what** something does and **why**, concisely.
They do not carry change history: no dates, no "was X, now Y", no incident
narrative, no "verified on <date>".

**Why:** history belongs in git and in project memory. In a comment it ages
badly, buries the actual rule, and costs a reader attention every time they
pass it.

**How to apply:** write the rule, not the story behind it. "A mode index is
meaningless on other hardware" beats "a Fire Stick build was deployed to a
Deck on 2026-08-06 and Kodi died with SIGFPE." Put the incident in a memory
entry and let the comment state the constraint. Applies to `data/*.yml`
comments as much as to Python.
