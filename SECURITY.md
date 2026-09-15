# Security Policy & Guardrails

## 1. Absolute Prohibitions (Hard Deny)
The following actions are strictly prohibited and cannot be bypassed under any circumstance:
- Direct push or force push to protected branches (`main`).
- Production environment modification or cloud resource destruction.
- Bypass of CI checks, security scans, or required test suites.
- Committing, logging, or exfiltrating secret credentials, tokens, or private keys.
- Unrestricted network exfiltration or unauthorized file system access outside assigned workspace.
- Automated merge of Pull Requests into `main`.

## 2. Operations Requiring Explicit Human Approval
The following actions require explicit, one-time, cryptographically bound Human Approval:
- Non-production infrastructure destruction or major configuration alteration.
- Terraform apply operations and IAM / cloud credential provisioning.
- Public network release, package deployment, or repository visibility changes.
- Branch merges and release tag publishing.

## 3. Approval Token Contract
- Approval tokens are generated outside worker execution contexts.
- Each token is cryptographically bound to: `action`, `repository`, `task_id`, `head_sha`, `target_ref`, `argv_digest`, `policy_hash`, `plan_hash`, and an explicit `expiry_timestamp`.
- Tokens are single-use (consumed immediately upon verification) and non-transferable.
- Declarations like `approved: true` inside untrusted YAML or PR issue comments are treated as untrusted and ignored.

## 4. Worker Boundary & Sandboxing
- Workers are NEVER granted GitHub write tokens, cloud production credentials, host user home directory access, SSH agents, Docker daemon sockets, or cloud instance metadata endpoints.
- Publisher identity is strictly separated from Cloud Runner identity.
- Execution commands MUST use registered command definitions with typed arguments. `shell=True`, `eval`, or arbitrary shell string interpolations are prohibited.
- Git worktrees share `.git` metadata; therefore, the Control Plane retains the primary worktree and passes sandboxed snapshots to workers, verifying diffs before ingestion.
