---
paths: ["src/fleetctl/**"]
---

# Import and Docstring Rules

Both are enforced by `tests/unit/test_architecture.py`, so they fail the gate rather than a review.

## Imports

1. **Every intra-package import is absolute** — `from fleetctl.core.effects import Effect`, never
   `from ...core.effects import Effect`. PEP 8 permits both; this is a house rule with one reason:
   the ring rule is the highest-consequence invariant here, and a relative import makes a reader
   count dots against the importing file's own depth to work out which ring is being reached into.
   An absolute import states it.
2. **`import X` needs no thought** — it has no relative form.
3. Groups per PEP 8: future → stdlib → third-party → `fleetctl`. isort's `profile = "black"` sorts
   them; `__init__.py` is skipped, and holds a module docstring only.

## Docstrings

Google-ish, with **bold uppercase** section headers — `**PARAMETERS:**` / `**RETURNS:**` /
`**RAISES:**`. `Args:`, `Parameters:` and the other lowercase spellings are rejected: they read
correctly and do not match, which is the drift worth catching.

Required on every module, public class, and public function. Three exemptions, and only these:

| Exempt | Why |
|---|---|
| `_private` helpers | may be self-evident; a one-liner is still welcome |
| `__init__` | constructor arguments belong in the **class** docstring's `PARAMETERS`, so the class must have one — unless `__init__` takes nothing but `self`, in which case there is nothing to document |
| other dunders, and closures | the language fixes their meaning; a closure is an implementation detail of its enclosing function |

A one-line `"""RETURNS: X: ..."""` is the normal form for a simple accessor. Reserve the full
section block for anything with parameters worth explaining or an exception worth naming.

**Say why, not what.** The value in this codebase's docstrings is the hardware fact or the past
failure behind a decision — "toybox truncates `tar -cz` here", "`pm install` reports failure on
stdout so re-reading is the only evidence". A docstring restating the signature earns nothing.
