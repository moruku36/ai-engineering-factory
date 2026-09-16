# Approved offline execution and recovery

`ApprovedContainerAdapter` connects the offline Linux runner to `RunLoopController`.
Overall status remains **MANUAL_ONLY**: Human authentication, native Antigravity
transport and artifact/commit validation are still unavailable. CLI `approve` remains
blocked. CI issues tokens with an explicit test-only issuer and does not prove Human
identity. `ApprovalManager` is an integrity/consumption primitive, not authentication.

## Trusted setup

The controller supplies a provisioned `OfflineContainerRunner`, `ApprovalManager`,
task-ID keyed plans, task-ID keyed token IDs and a private adapter state directory.
Each plan contains `repository`, `head_sha`, `target_ref`, `policy_hash`, `plan_hash`,
`command_id` and a flat mapping of input bytes. Plan and command registration are
control-plane actions; do not let a worker configure them or issue tokens.

`approval_context(manifest, worktree_reference)` previews the fields an external
trusted issuer must approve. The execution digest covers the immutable image ID,
registered argv/timeout, profile version, network denial, every input file hash,
full task manifest and worktree reference. The adapter snapshots execution inputs
before consumption, so subsequent caller changes cannot change approved bytes.
Profile semantics changes must increment the version and require new approval.

The loop checks plan/policy/base against the state ledger before dispatch. The
worktree reference is bound metadata only: the container never mounts it, and the
adapter does not claim to validate Git ancestry or produce a candidate commit.

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
identity and reconciles the corresponding container journal, then returns BLOCKED.
The lease and task claim remain for operator review. A live or uncertain controller,
changed context, missing lease or unconfirmed container cleanup stops recovery.
Recovery must be serialized by the trusted control process. There is no background
supervisor and no automatic clearing of blocked records.

## Validation boundary

Unit tests exercise changed input/manifest/image/argv/timeout/repository/ref/hash
rejection, concurrent claims, token replay across databases, persisted-result recovery,
live-controller refusal, ledger drift and input snapshot consistency. Real Docker CI
additionally covers approval-to-loop execution, denied binding before Docker starts,
and killing a controller during an approved run followed by orphan cleanup without
redispatch. Test-only token issuance is not a production authorization workflow.

Next: authenticated issuance and protected key provisioning, candidate artifact import
with independent validation, controlled model API networking, and native transport.
