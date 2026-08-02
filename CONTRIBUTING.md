# Contributing

## Setup

```bash
uv sync --all-extras
uv run pytest
```

## Before opening a pull request

```bash
uv run black src tests
uv run isort src tests
uv run mypy
uv run pytest
```

CI runs exactly these, on Python 3.12 and 3.13.

## House style

- `from __future__ import annotations` at the top of every module.
- Modern typing: `str | None`, `list[T]`, `dict[K, V]`. Everything annotated;
  `mypy --strict` must pass.
- Black and isort with `line-length = 160` (configured in `pyproject.toml`).
- Docstrings on every public module, class, and function — see the exact
  format below.
- `LOGGER = logging.getLogger(__name__)` at module level; `%s` lazy
  formatting, never f-strings in log calls.
- `Protocol` for seams, frozen dataclasses for value objects, Pydantic for
  anything parsed from YAML or crossing a wire.
- `__init__.py` holds a module docstring only — no re-exports, no `__all__`.

## Docstring format

Google-style with **bold** section headers, 4-space-indented entries,
backticked names, parenthesized types, and a trailing `<br>` on each entry.
Omit a section that doesn't apply — don't write `**RETURNS:** None`.

```python
def push_file(self, local_path: Path, remote_path: str, *, verify: bool = True) -> int:
    """Upload a file to the device and return the number of bytes written.

    One-paragraph elaboration when the behaviour isn't obvious from the
    summary — constraints, ordering, or why it works this way.

    **PARAMETERS:**
        `local_path` (Path): File to upload.  <br>
        `remote_path` (str): Destination path on the device.  <br>
        `verify` (bool, optional): Whether to md5-check the result. Defaults to ``True``.  <br>

    **RETURNS:**
        `int`: Bytes written to the device.  <br>

    **RAISES:**
        `TransportError`: If the transfer fails or the digest doesn't match.  <br>
    """
```

The trailing `<br>` is load-bearing: a plain two-space Markdown line break
gets stripped by Black, and the entries then run together when rendered.

## Tests

AAA (Arrange / Act / Assert) with a blank line between phases. Mock every
external: no test may require a real device, a real network, or a real SMB
share. If something can only be tested against hardware, that is a design
problem with the seam, not a reason to skip the test.

## Things that will get a PR sent back

- **Real device data.** No real IPs, MAC addresses, hostnames, serials, or
  credentials anywhere — code, tests, docs, comments, fixtures. Use
  `192.168.1.50` and `aa:bb:cc:dd:ee:ff`.
- **Secrets as values.** Config holds `!ref` pointers; values resolve at the
  edge.
- **A destructive step not declared destructive.** Effect classification is
  what the policy layer keys off.
- **Unvalidated interpolation into a device shell.**
- **A device-specific workaround in `core/`.** Vendor quirks belong to the
  pack that has them, as data.

## Adding a pack

Device packs and app packs register through entry points — see
[docs/architecture.md](docs/architecture.md) §7. A pack should not need any
change in `core/` to work. If it does, that is worth raising as an issue:
the seam is probably in the wrong place.
