# Architecture Overview

## 1. System Vision
AI Engineering Factory operates as a software factory where agents act as specialized labor under strict engineering control. The system guarantees that every code change is validated, reviewed, and traceable to an immutable schema-compliant specification.

## 2. Control Plane & Execution Engine
- **Control Plane**:
  - `Schema Validator`: Strict rejection of unknown fields, duplicate keys, circular dependencies, oversized payloads (>1 MiB), deep nesting (>20).
  - `Policy Engine`: Hard deny rules (direct push to main, production destroy, credential leak) and soft approval enforcement.
  - `State Ledger`: CAS-based single writer maintaining state sequence.
  - `Scheduler`: DAG-based dependency resolution with resource exclusivity (ports, locks, DB migrations).
- **Execution Engine (Adapter Layer)**:
  - Abstracts interaction with agent environments (Antigravity CLI/SDK, manual CLI, subagent sessions).
  - Isolates agent execution from direct control plane manipulation.
