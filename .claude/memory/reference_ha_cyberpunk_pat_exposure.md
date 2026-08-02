---
name: a GitHub PAT is embedded in ha-cyberpunk's git remote URL
description: The sibling ha-cyberpunk repo stores a personal access token in plaintext inside its git remote URL. Do not replicate the pattern; fleetctl's remote is clean.
type: reference
---

`ha-cyberpunk`'s `origin` remote is of the form `https://<user>:<github_pat_...>@github.com/...`, embedding a live GitHub personal access token in plaintext in `.git/config`. Found 2026-08-01 while setting up `fleetctl`; surfaced to the user, who should rotate it.

`fleetctl`'s remote is deliberately the clean form — `https://github.com/salvuswarez/fleetctl.git` — with authentication left to the git credential manager.

**Why:** A token in a remote URL leaks into terminal scrollback, CI logs, screen shares, `git remote -v` output, and any tool that reads the repo config. It is also long-lived and usually broadly scoped.

**How to apply:** Never set a `fleetctl` remote with credentials inline. If a push fails to authenticate, fix it via the credential manager or a `gh auth login`, not by embedding a token. When reading any sibling repo's git config, treat the output as sensitive and do not echo it into a document, commit message, or issue.
