# ADR-0001: Core Technology Stack & Isolation Model

## Status
Accepted

## Context
The AI Engineering Factory requires a robust, minimal, and deterministic foundation. We must avoid heavy infrastructure dependencies (Redis, Kubernetes, Vector DBs, heavy Agent frameworks) while ensuring safety, reproducibility, and rigorous isolation.

## Decisions
1. **Language & Core Runtime**: Python 3.11+, PyYAML (safe loader only), JSON Schema 2020-12 (`jsonschema`).
2. **Quality Tooling**: `pytest` for unit/integration/negative tests, `ruff` for linting and formatting.
3. **State Management**:
   - Single-writer state ledger with CAS revision check.
   - Phase 1 & 2: File-based JSON ledger in repository for verifiable audit trails.
   - Phase 3: SQLite in `runtime-root` for transactional lease and execution state.
4. **Isolation Boundaries**:
   - `runtime-root` outside the Git repository for transient runtime data (PIDs, DBs, leases, raw logs).
   - Git worktrees inside `runtime-root` with diff validation before ingestion.
5. **No Heavy Frameworks**: No LangChain, CrewAI, AutoGen, Redis, or Kubernetes. All control plane logic is implemented in self-contained, typed Python modules.

## Consequences
- Zero external daemon dependencies for base operation.
- High testability with fast local feedback.
- Deterministic behavior and clear threat modeling.
