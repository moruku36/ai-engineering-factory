# AI Engineering Factory

[English](README.md) | [日本語](README.ja.md)

An experimental governance layer for AI-assisted software development, combining isolated execution, evidence, phase contracts, and human-approved pull requests. Current operation is Experimental / MANUAL_ONLY.

## Current capabilities

The factory governs bounded Builder, Tester, and Reviewer work with task profiles, command registries, isolated execution, evidence, and approval boundaries. It is experimental and operates in MANUAL_ONLY mode; it is not a fully autonomous production development platform.

Read [PROJECT_STATE.md](PROJECT_STATE.md) for current limits and the [quickstart](docs/getting-started.md) for the supported workflow. Linux container isolation is CI-verified with Docker; Windows does not support that Linux-container isolation path, and macOS expectations are not equivalent to CI verification.

## Local checks

```bash
pip install -e ".[dev]"
python -m orchestrator.cli doctor
ruff check orchestrator scripts tests
python scripts/secret_scan.py
python scripts/audit_dependencies.py
pytest -v tests/
```

The doctor command's exit code 2 can mean a healthy MANUAL_ONLY environment as documented in the original guide.

[Architecture](ARCHITECTURE.md) · [Operations](OPERATIONS.md) · [Security](SECURITY.md) · [Case study](docs/case-studies/web-security-control-lab.md).


## Contents

- [ARCHITECTURE.md](ARCHITECTURE.md)
- [OPERATIONS.md](OPERATIONS.md)
- [PROJECT_STATE.md](PROJECT_STATE.md)
- [SECURITY.md](SECURITY.md)
- [config/](config)
- [docs/](docs)
- [hooks/](hooks)
- [orchestrator/](orchestrator)

## Detailed documentation

For offline manifest and receiver byte checks, see [Local artifact handoff v0.1](docs/operations/HANDOFF_V01.md). This bounded tool records COLLECTED only; independent acceptance verification remains separate.

The [Japanese guide](README.ja.md) retains the complete original setup instructions, configuration, examples, project status, and limitations. Supporting documents keep their existing language.
