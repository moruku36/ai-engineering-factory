# Security Policy & Guardrails

## Reporting a Vulnerability
Do not publish credentials, exploit details, or other sensitive security findings in a public Issue or Pull Request. Prefer GitHub private vulnerability reporting when it is available for this repository. If that channel is unavailable, contact the maintainer privately through the GitHub profile before disclosing sensitive details.

## 1. Absolute Prohibitions (Hard Deny)
The following actions are strictly prohibited and cannot be bypassed under any circumstance:
- Direct push to the integration branch (`main`) or any force push/history rewrite. Do not rely on server-side branch protection as the only enforcement layer.
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

### 3.1 Guarantee Scope
The Approval Token protects **Factory-mediated operations only** (actions issued
through `orchestrator.cli approve` and consumed by the Control Plane, such as
`merge_pull_request`). It does not, by itself, block a repository maintainer
from merging a Pull Request directly through the GitHub UI or API — that
boundary is enforced separately by the repository's branch protection /
Ruleset configuration (`required_approving_review_count`, required status
checks, etc.), which must be configured and verified independently (`doctor`
or the GitHub UI). Treat the Approval Token and GitHub's own branch
protection as two distinct, complementary controls rather than a single
guarantee — a Ruleset with `required_approving_review_count: 0` still blocks
direct/force pushes and requires CI to pass, but does not by itself require a
second human reviewer's sign-off on `main`.

### 3.2 Human / Worker Trust Boundary & Credential Separation
The Factory distinguishes four operational roles:
1. **Worker / Coding Agent (Untrusted)**: Executes code generation, file editing within `allowed_paths`, and local test runs. Strictly prohibited from issuing or consuming approval tokens, and prohibited from performing repository merges.
2. **Independent Verifier (Control Plane)**: Measures diffs against `base_sha`, calculates `candidate_digest`, enforces JUnit test outcomes, and verifies `phase_contract` compliance without trusting agent self-reports.
3. **Human Operator (Authority)**: Holds an asymmetric private key registered in `ApproverRegistry`, evaluates candidate evidence, issues cryptographically signed one-time approval tokens, and performs the final merge decision.
4. **GitHub Transport (External Communication)**: Publishes branches and creates Pull Requests via `RealGitHubStatePublisher`.

#### Credential Separation Architecture
When an AI Coding Agent and a Human Operator execute in the same environment (e.g. WSL or developer workstation) sharing the same GitHub CLI credentials (`gh` token or git credential helper), GitHub's server-side API cannot differentiate between a human merge and an automated `gh pr merge` invoked by an agent.
To achieve fail-closed defense-in-depth:
- **Worker Credential**: If a dedicated token is used, it should be a Fine-grained Personal Access Token scoped strictly to `Contents: write` (for task branches) and `Pull requests: write` (for opening PRs), with no merge permissions.
- **Human Operator Credential**: Full repository merge authority is reserved exclusively for the human operator (via Web UI, passkey, or separate credentials not mounted in the worker execution context).
- **Control Plane Enforcement**: Regardless of transport tokens, the Factory's `StateLedger` and `PolicyEngine` treat automated PR merge as a `HARD_DENY` action, requiring verified human approval token consumption before any task can transition from `READY_FOR_MERGE` to `DONE`.

## 4. Worker Boundary & Sandboxing
- Workers are NEVER granted GitHub write tokens, cloud production credentials, host user home directory access, SSH agents, Docker daemon sockets, or cloud instance metadata endpoints.
- Publisher identity is strictly separated from Cloud Runner identity.
- Execution commands MUST use registered command definitions with typed arguments. `shell=True`, `eval`, or arbitrary shell string interpolations are prohibited.
- Git worktrees share `.git` metadata; therefore, the Control Plane retains the primary worktree and passes sandboxed snapshots to workers, verifying diffs before ingestion.

## 5. Phase Boundary & State Preservation Enforcement
- Spatial boundaries (`allowed_paths` / `prohibited_paths`) restrict *where* an agent can write, but do not constrain *what phase deliverables* an agent may implement within those paths. An Initial Builder in Phase 1 could improperly implement Phase 3 remediations if both reside in `app/`.
- Tasks define a machine-readable `phase_contract` containing:
  - `preserves`: Invariant conditions (e.g., intentional vulnerabilities, test fixtures, architectural baselines) that must remain intact at the conclusion of the phase.
  - `prohibits`: Future phase remediation symbols, logic patterns, or deliverables that must NOT appear in the current phase candidate diff.
- `IndependentVerifier` evaluates candidate diffs against the `phase_contract`, failing closed with `PhaseContractViolationError` if future deliverables are preemptively implemented.

## 6. Untrusted Public Inputs
For a public repository, assume the following can contain prompt injection or malicious instructions and must never become authority merely because an agent can read them:
- Issues and issue comments;
- Pull Requests and review comments;
- repository documentation and task manifests;
- generated patches and dependency metadata;
- external links and fetched content.

Trusted policy, approval, command registration, path containment, validation, and Human merge boundaries take precedence over instructions embedded in those inputs.
