# AI Engineering Factory

[English](README.md) | [日本語](README.ja.md)

**Experimental / MANUAL_ONLY** · Python 3.11+

## 1. What it does

A task, verification, and approval framework for edits made by a person or an external agent. It does not write code autonomously. Flow: task/edit -> checks -> PR -> human approval. Nothing is merged or deployed automatically.

## 2. Structure

- `orchestrator/`: state, policy, execution, approval, GitHub checks
- `schemas/`, `tasks/`, `config/`, `tests/`, `scripts/`, `.github/`: contracts, templates, CI
- `docs/`: details. Databases, logs, and credentials stay outside the repo.

## 3. Implemented, unimplemented, unverified

**Implemented:** task schema and scheduling; offline Linux container execution, collection, and an independent verifier; single-use signed human approvals with a journal; branch and PR API. Receipts record only `COLLECTED`, never `VERIFIED` or `COMPLETE`. Windows credential and RunPod startup code is off by default and needs separate human approval.

**Not provided:** automatic merge or deploy; native Claude Code or Codex adapters; Antigravity is blocked in the current Factory.

**Limits and unverified:** complete-diff handling is limited, and handoff rejects such tasks. Isolation is Linux-only. CI covers ordinary Ubuntu and Windows; macOS and WSL2 are unverified. Synthetic tests are not proof of live keys, GPUs, Windows Hello, or Mattermost. Stopping a process does not prove Pod deletion or billing has stopped.

### Safety model

High-impact changes need human approval. The Factory fails closed: if a required check or control is unavailable, it stops instead of silently falling back to a weaker mode. Secrets stay out of chat and logs.

## 4. Shortest start

Use a Python 3.11+ virtualenv and activate it as described in the quickstart.

```bash
git clone https://github.com/moruku36/ai-engineering-factory.git
cd ai-engineering-factory
pip install -e ".[dev]"
python -m orchestrator.cli doctor
python -m orchestrator.cli demo --task-file tasks/templates/basic-task.yaml --worktree .
```

`doctor` exit code 2 is expected when checks pass (MANUAL_ONLY). The demo only checks trusted, existing edits: no AI launch, isolation, path enforcement, or independent evidence.

## 5. Docs

[Project state](PROJECT_STATE.md) · [Architecture](ARCHITECTURE.md) · [Operations](OPERATIONS.md) · [Security](SECURITY.md) · [Quickstart](docs/getting-started.md) · [Adapters](docs/adapters/README.md) · [Compatibility](docs/compatibility/matrix.md) · [Handoff](docs/operations/HANDOFF_V01.md) · [Startup credentials (Japanese)](docs/security/runpod-startup-credential.ja.md)

[MIT License](LICENSE)
