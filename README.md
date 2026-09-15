# AI Engineering Factory

Autonomous AI Engineering Factory for multi-agent software development, verification, and governance.

## Overview
AI Engineering Factory is a robust, schema-driven, multi-agent development system that executes structured engineering tasks with strict security guardrails, verifiable state machines, and human-in-the-loop approvals.

## Quick Reference
- [Architecture](ARCHITECTURE.md): System design, Control Plane vs Worker separation, and data flow.
- [Security Policy](SECURITY.md): Threat model, sandbox boundaries, and approval contracts.
- [Operations Guide](OPERATIONS.md): Runtime operations, recovery, and inspection.
- [Contributing Guide](CONTRIBUTING.md): PR workflow, branch naming, and testing standards.
- [Agent Specifications](AGENTS.md): Roles, capabilities, skills, and execution contracts.
- [Project State](PROJECT_STATE.md): Current lifecycle phase and execution ledger status.

## Directory Layout
- `docs/`: In-depth documentation (Architecture, ADR, Security, Operations, Compatibility).
- `schemas/`: JSON Schema 2020-12 specifications for Tasks, Plans, Results, and State.
- `orchestrator/`: Control Plane implementation and execution engine adapters.
- `tasks/`: Task manifests, execution plans, and example workflows.
- `state/`: Verified state projections and event logs.
- `hooks/`: Lifecycle verification hooks.
- `config/`: Operational profiles and permission boundaries.
