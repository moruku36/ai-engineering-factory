# Architecture Specification (v1.0)

## 1. Core Principles
- **Separation of Control Plane and Worker**: The Control Plane manages schemas, policies, states, scheduling, leases, and publishing. Workers only execute assigned steps within sandbox boundaries.
- **Single State Writer**: State transitions are serialized through a single writer using Compare-And-Swap (CAS) revision semantics. Distributed Git locking is forbidden.
- **SoT and Runtime Isolation**:
  - GitHub `main` branch is the Source of Truth for verified code and specifications.
  - Dedicated `factory/state` branch holds non-secret operational audit trails.
  - Runtime databases, PIDs, active leases, raw session logs, and credentials reside strictly outside the repository in `runtime-root`.
- **Adapter-Driven Execution**: Antigravity is accessed via execution adapters. Core unit tests must run fully with manual/mock adapters.

## 2. Component Architecture
```
+----------------------------------------------------------------+
|                         Control Plane                          |
|  +------------+  +------------+  +-------------+  +---------+  |
|  |   Schema   |  |   Policy   |  |    State    |  | Lease & |  |
|  |  Validator |  |   Engine   |  |   Ledger    |  |Scheduler|  |
|  +------------+  +------------+  +-------------+  +---------+  |
+--------------------------------+-------------------------------+
                                 | Task Dispatch (Worktree / Snapshot)
                                 v
+----------------------------------------------------------------+
|                         Worker Layer                           |
|  +--------------------+  +------------------+  +------------+  |
|  |  Builder Agent     |  |  Tester Agent    |  |  Reviewer  |  |
|  |  (Isolated Session)|  |  (Isolated Test) |  |   Agent    |  |
|  +--------------------+  +------------------+  +------------+  |
+--------------------------------+-------------------------------+
                                 | Candidate Results & Evidence
                                 v
+----------------------------------------------------------------+
|                        Execution Engine                        |
|  +----------------------------------------------------------+  |
|  | Antigravity Adapter / Manual Adapter / Subagent Runtime   |  |
|  +----------------------------------------------------------+  |
+----------------------------------------------------------------+
```

## 3. Data Flow
1. **Task Ingestion**: Task YAML is validated against JSON Schema 2020-12. Spec digest is calculated.
2. **Scheduling**: DAG dependency resolution, resource isolation (ports, locks, DB), and concurrency limit.
3. **Dispatch**: Control Plane prepares isolated worktree in `runtime-root` and passes verified snapshot.
4. **Execution & Validation**: Builder executes commands via registered commands (no `shell=True`). Tester and Reviewer independently verify.
5. **State Progression**: State advances from `PROPOSED` to `READY`, `RUNNING`, `VALIDATING`, `REVIEW`, `READY_FOR_MERGE`, and finally `DONE` upon verified human merge.
