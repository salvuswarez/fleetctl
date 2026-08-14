---
paths: ["tests/**"]
---

# Test Rules

1. **No test touches real hardware, a real network, or a real SMB share** — if something can only be tested against a device, the seam is wrong. Fix the seam.
2. **AAA with blank lines between phases** — Arrange, Act, Assert. One behaviour per test.
3. **Assert on effects, not on mock internals** — prefer "the audit stream recorded 90 `pm disable-user` events, all `OK`" over inspecting a mock's `call_args_list`.
4. **Use the real test adapters** — `FakeTransport`, `LocalArtifactStore`, `InMemoryAuditSink` are shipped seam implementations, not mocks. They are the second adapter that makes each seam real.
5. **Transforms get fixture directories** — build a small tree in `tmp_path`, run the transform, assert on the resulting tree.
6. **No real device data in fixtures** — `192.168.1.50`, `aa:bb:cc:dd:ee:ff`, invented device names.
7. **Test names state the behaviour** — `test_probe_returns_none_when_model_is_empty`, not `test_probe_2`.
8. **Parametrize instead of looping** — a failing case should name itself in the report.
9. **Every test file lives under `tests/unit/`**, never directly in `tests/`.
10. **Script a double from output actually observed on hardware**, never from an assumed CLI. A `FakeTransport` scripted from a guess keeps the suite green while the device answers something else — that is how a missing `hostname` binary and an unsupported `--show-version` flag both shipped.
11. **A test that cannot fail is worse than no test.** One in this repo runs `git` from the wrong directory and has never checked anything while passing. When a test guards something expensive, prove it fails when the guarded property is broken.
