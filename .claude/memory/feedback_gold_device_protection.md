---
name: prefer proving fixes on a disposable device first
description: A situational preference, not a standing rule — during one debugging session the user asked that a fix be encoded in the pipeline and proven on a disposable device rather than hand-applied to the capture source.
type: feedback
---

**Scope correction (2026-08-02):** the user clarified this was *"just a one
time or not really a hard rule in my case."* Treat it as a sensible default
when a change is unproven, not as an inviolable constraint, and do not
describe the capture source as permanently off-limits.

The gold source device is the one the whole capture → build → deploy pipeline depends on. The user's standing instruction, given when a fix was about to be hand-applied to it: *"fix it in our tooling, then apply it to the [disposable] device to test. [gold] should only be deployed to once we know everything is perfect. cant mess that one up."*

**Why:** If the gold source is broken by an unproven experimental change, every future capture inherits the breakage. Every other device is disposable — recoverable by redeploying.

**How to apply:** (1) Encode the fix as a transform or config in the build pipeline, never as a one-off manual edit; (2) test-deploy to a disposable device; (3) only then consider whether the gold source should be touched, preferring a redeploy of the corrected profile over hand-editing.

`fleetctl`'s policy layer (S4) can express this — a device can be marked protected against named steps — but it is **off by default** and no device is protected unless someone writes the rule. The capability matters most for the MCP adapter (S6), where a non-human caller cannot read a convention; it is not a claim that any particular device must be protected. See [[architecture_new_repo_not_refactor]] for stage ordering.
