# Agent Role Specifications

## 1. Roles Overview
| Role | Primary Responsibility | Constraints & Boundaries |
|---|---|---|
| **Builder** | Implementation of code, configuration, tests | Restricted to assigned `allowed_paths`, command execution via registry only |
| **Tester** | Independent verification and test execution | Isolated execution session, read-only access to builder workspace, generates test evidence |
| **Reviewer** | Code quality, security, and schema review | No write access to source code, emits structured review verdicts (`APPROVED`, `CHANGES_REQUESTED`) |

## 2. Execution Protocol
- Agents operate strictly within their allocated worktree and execution lease.
- Permissions are dictated by signed task profiles.
- Agents cannot alter task state or permissions directly; all status updates are mediated by the Control Plane.
