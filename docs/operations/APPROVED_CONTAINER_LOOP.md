# Approved offline execution and recovery

`ApprovedContainerAdapter` connects the offline Linux runner to `RunLoopController`.
Overall status remains **MANUAL_ONLY**.

Authenticated issuance is implemented in the CLI function `cmd_approve(args)`. It
constructs `ApprovalManager(approvals_dir=args.approvals_dir, enforce_authentication=True)`
and calls `issue_authenticated_token`, which checks the operator key fingerprint and
`ApproverRegistry` identity and action permissions. Without protected valid keys and a
registry it blocks. Two mechanisms are distinct: HMAC token integrity and single use
(`ApprovalManager`), and approver identity and action permission (`ApproverRegistry`).
CI issues tokens with an explicit test-only issuer, which is not evidence of a real human
identity. Protected registry and key provisioning in a real deployment is still required;
what is missing is that deployment, not authentication code.

A snapshot, collector and verifier exist, but deletion, file-mode and complete-diff
limits remain. The adapter does not generate an autonomous candidate commit and does not
perform a merge; human merge verification exists elsewhere in the project. There is no
native Antigravity transport (unavailable).

## Trusted setup

The controller supplies a provisioned `OfflineContainerRunner`, `ApprovalManager`,
task-ID keyed plans, task-ID keyed token IDs and a private adapter state directory.
Each plan contains `repository`, `head_sha`, `target_ref`, `policy_hash`, `plan_hash`,
`command_id` and a flat mapping of input bytes. Plan and command registration are
control-plane actions; do not let a worker configure them or issue tokens.

`approval_context(manifest, worktree_reference)` previews the fields an external
trusted issuer must approve. The execution digest covers the immutable image ID,
registered argv/timeout, profile version, network denial, every input file hash,
full task manifest and worktree reference. The adapter copies the registered plan and input mapping
before consumption, so later changes to that mapping cannot change its approved input bytes.
The worktree reference is bound, but the snapshot digest is not part of this token binding;
candidate binding is proposed in G2.
Profile semantics changes must increment the version and require new approval.

The loop checks plan/policy/base against the state ledger before dispatch.

## Worktree handling

When the worktree reference is a real directory (`Path(worktree_path).is_dir()`):

- `snapshot_worktree` copies it into a private `workspace_snapshot`.
- `ArtifactCollector` collects from that source snapshot.
- `compute_base_file_digests` uses the approved `head_sha`. If the base is unavailable, the error is caught and `base_files=None`; the result is then best-effort and not diff-verified.
- The runner receives `workspace_mount=snapshot_dir`, and the snapshot is mounted read-only. The original source path is not mounted directly.
- `IndependentVerifier` runs the actually collected candidate against the actual worktree.
- The adapter does not claim to validate Git ancestry and produces no candidate commit.

Bare fixture references (not real directories) keep the legacy output-collection fallback.
The handoff currently rejects tasks requiring complete-diff evidence, including an
unknown base; partial verifier output is not upgraded to complete-diff evidence.

Use `max_workers=1`. This profile is synchronous and extends its lease to cover the
bounded Docker calls and command timeout. Parallel native agents and live cancellation
are not implemented. All databases, journals and signing keys must remain in protected
control storage outside source/worker inputs. Linux adapter state must be owner-only
mode 0700. Windows unit tests do not establish Windows runtime isolation or ACLs.

## Dispatch and recovery semantics

1. Persist a unique task claim and run ID before approval consumption.
2. Verify/consume the context-bound token atomically, then invoke the isolated runner.
3. Persist results only after runner cleanup confirmation. Nonzero exit is FAILED.
4. On success, the loop advances only to VALIDATING, with no fabricated candidate SHA,
   independent review, merge or downstream completion.

One task ID can dispatch once in this adapter database. Retries require explicit new
planning/task identity and new approval; deleting the database or reissuing a token
is not a recovery procedure. Approval and execution databases are separate: a crash
between commits can sacrifice availability, but must never authorize a silent retry.

When initialization finds a RUNNING task, the adapter can read its saved result without
re-execution. If the prior controller died before saving a result, it checks process
identity and reconciles the corresponding container journal, then returns BLOCKED
(uncertainty stays blocked). The lease and task claim remain for operator review. A live
or uncertain controller, changed context, missing lease or unconfirmed container cleanup
stops recovery. Recovery is manual-only and must be serialized by the trusted control
process. There is no automatic redispatch, no background supervisor and no automatic
clearing of blocked records.

## Validation boundary

Unit tests exercise changed input/manifest/image/argv/timeout/repository/ref/hash
rejection, concurrent claims, token replay across databases, persisted-result recovery,
live-controller refusal, ledger drift and input snapshot consistency. Real Docker CI
additionally covers approval-to-loop execution, denied binding before Docker starts,
and killing a controller during an approved run followed by orphan cleanup without
redispatch. This validation is limited to those cases; it does not establish a complete
diff guarantee, and an unknown base remains a limitation. Test-only token issuance is not
a production authorization workflow.

Next (still unresolved): complete-diff handling for candidate artifacts (deletion, mode,
rename, unknown base) with independent validation, protected deployment of operator keys
and the approver registry, controlled model API networking, native transport, and the
governance contracts proposed in the [governance roadmap](../architecture/governance-roadmap.md).
