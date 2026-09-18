# Compatibility Matrix

Status legend: **CI Verified** — exercised on every push/PR by `.github/workflows/ci.yml`.
**Manually Verified** — run and confirmed by a maintainer outside CI, not continuously checked.
**Expected** — should work based on `requires-python`/code constraints, but is untested.
**Unsupported** — known not to work or explicitly out of scope.

| Component | Status | Versions | Notes |
|---|---|---|---|
| **Python** | CI Verified | 3.11.x | `ci.yml` pins `python-version: "3.11"`. `pyproject.toml` declares `requires-python = ">=3.11"`; 3.12+ is Expected but not exercised by CI. |
| **OS** | CI Verified | Ubuntu (`ubuntu-latest`), Windows (`windows-latest`) | Both `ci.yml` matrix legs. Cross-platform path handling (`Path`, `PurePosixPath`) is used throughout. |
| **OS** | Expected | macOS | Not in the CI matrix; the offline container boundary (`OfflineContainerRunner`) additionally requires a local Linux Docker daemon and is skipped on non-Linux platforms at runtime. Docker Desktop being installed is not sufficient — it does not provide the Linux container isolation `OfflineContainerRunner` requires. |
| **OS** | Expected | WSL2 (Windows Subsystem for Linux) | Not in the CI matrix. The best candidate for running the offline container boundary on a Windows machine, since it provides a real Linux kernel/Docker daemon; not manually verified yet. |
| **Git** | Manually Verified | >= 2.34.0 | Tested with 2.40.0.windows.1; not pinned or version-checked in CI. |
| **Antigravity** | Unsupported (BLOCKED) | Native transport not implemented | Binary discovery is not a capability test; native and implicit fallback are refused. Select manual mode explicitly. See [ANTIGRAVITY_INTEGRATION_EVALUATION.md](../operations/ANTIGRAVITY_INTEGRATION_EVALUATION.md). |
| **JSON Schema** | CI Verified | Draft 2020-12 | Validated via `jsonschema==4.26.0`, exercised by `tests/unit/test_schema.py`. |
| **YAML** | CI Verified | 1.2 (SafeLoader only) | PyYAML 6.0.3. |
| **Docker** | CI Verified (Linux only) | Local daemon, Linux containers, seccomp `builtin` profile required | Exercised by the `container-boundary` CI job (`ubuntu-latest` only); not run on Windows/macOS. |
