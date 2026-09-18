# Getting Started

This is the one-scenario walkthrough: clone the Factory, point it at your own
repository, run a task end-to-end, and see the resulting evidence. It should
take about 15 minutes.

If you want the "why" behind these steps, read the [README](../README.md)
first. This page is only the "how".

> **OS note**: full isolated execution (`OfflineContainerRunner`) requires a
> local Linux Docker daemon and is Linux-only today. Everything else in this
> walkthrough (CLI, `ManualAdapter`, verification, approval tokens) runs on
> Linux, Windows, and — expected but not CI-verified — macOS. See the
> [Compatibility Matrix](compatibility/matrix.md).

## 1. Clone and install

```bash
git clone https://github.com/YOUR_GITHUB_OWNER/YOUR_REPOSITORY.git ai-engineering-factory
cd ai-engineering-factory

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -e ".[dev]"
```

This also installs a console script, `ai-factory`, equivalent to
`python -m orchestrator.cli`. Both are used interchangeably below.

## 2. Check your environment

```bash
python -m orchestrator.cli doctor
```

This checks Python, Git, GitHub branch protection (if `gh` is authenticated
and a repository is detected), and the Antigravity native-runtime probe. A
clean environment still exits with code `2` — that is expected, not a
failure. It means **Execution Mode: MANUAL_ONLY**: every merge requires an
explicit Human approval token, by design (see [Safety Model](../README.md#safety-model)).

## 3. Point the Factory at your repository

```bash
python -m orchestrator.cli init --repository YOUR_GITHUB_OWNER/YOUR_REPOSITORY
```

`init` does two things:

- Creates a **runtime root** outside this git repository (default:
  `~/.ai-engineering-factory/runtime/<owner>__<repo>/`) — transient state
  (worktrees, leases, logs, SQLite DBs) is never committed to your repo.
- Writes a local config file at `.ai-factory/config.yaml` (already
  git-ignored) recording your repository and runtime root.

If you're running this inside the Factory's own repository as a demo, you
can pass `--repository moruku36/ai-engineering-factory` (or omit
`--repository`; it auto-detects from `git remote get-url origin` or
`$GITHUB_REPOSITORY`).

## 4. Write a task

Copy the template and fill in the placeholders:

```bash
cp tasks/templates/basic-task.yaml tasks/examples/my-task.yaml
```

Edit `tasks/examples/my-task.yaml`:

- `repository`: the `https://github.com/...` URL for the repo you ran `init`
  against.
- `allowed_paths` / `prohibited_paths`: the narrowest set of paths this task
  is allowed to touch. This is enforced, not advisory.
- `validation`: which command(s) must pass. `command_id` must be in the
  allowed command registry (`pytest`, `ruff`, `python`, `git`, `npm`, `node`
  by default — see `orchestrator/core/policy.py`).
- `output_artifacts`: files the task must produce for a run to count as
  `SUCCESS`.

You do not need a real AI agent to try this: for the demo step below, the
"builder" work is just whatever is already on disk in the worktree you point
it at (e.g. an existing branch, or a worktree you edited by hand or with any
coding agent of your choice).

## 5. Run it end-to-end (local demo)

```bash
python -m orchestrator.cli demo --task-file tasks/examples/my-task.yaml --worktree .
```

This runs your task through `ManualAdapter`: it executes the validation
command as a real subprocess (no `shell=True`, sandboxed environment, policy
checked), then hashes the declared `output_artifacts` to produce evidence.

**This demo path is intentionally not isolated** — it runs directly against
the worktree you pass it, with no network/filesystem boundary. It exists to
show the task → validation → evidence shape quickly. Do not point it at
untrusted code. For the real isolation boundary, see step 6.

You should see something like:

```text
=== Demo: task TASK-001 via ManualAdapter (worktree=/path/to/repo) ===
[*] Executing validation step: pytest
    -> PASS (exit=0)
=== Result: SUCCESS ===
  artifact: reports/task-001-report.json -> 3f9a...c1
```

## 6. The real isolation + verification path

Once the shape above makes sense, the production path replaces
`ManualAdapter` with the offline container boundary and independent
verification. This needs a local Linux Docker daemon and a pre-provisioned
immutable image (`sha256:` ID, never a mutable tag):

```python
from orchestrator.core.container import ContainerCommand, OfflineContainerRunner
from orchestrator.core.artifacts import ArtifactCollector
from orchestrator.core.verifier import IndependentVerifier
from orchestrator.core.worktree import snapshot_worktree, compute_base_file_digests

# 1. Registered command_id -> exact argv; no free-form argv is ever accepted.
runner = OfflineContainerRunner(
    control_root="/path/to/runtime-root/TASK-001",
    image_id="sha256:" + "0" * 64,  # from `docker image inspect`
    commands={"pytest": ContainerCommand(argv=("/usr/local/bin/pytest", "tests/unit/"))},
)

# 2. Snapshot only git-tracked files from the worktree (already builder-edited)
#    and mount that snapshot read-only into the container.
snapshot_dir, _digest, _files = snapshot_worktree(worktree_dir, "/path/to/runtime-root/TASK-001/snapshot")
result = runner.run("pytest", run_id="run-001", workspace_mount=snapshot_dir)

# 3. Collect the snapshot's source (not the container's own output) and
#    compute a genuine diff against base_sha.
collector = ArtifactCollector(allowed_paths=["src/"])
artifacts = collector.collect(snapshot_dir, "/path/to/runtime-root/TASK-001/collected")
base_files = compute_base_file_digests(worktree_dir, base_sha, allowed_paths=["src/"])

# 4. Independently verify: reject the worker's self-reported claim, measure
#    candidate_digest from the real diff, and parse JUnit XML if produced.
verifier = IndependentVerifier()
evidence = verifier.verify_candidate(
    task_id="TASK-001",
    base_sha=base_sha,
    artifacts=artifacts,
    execution_exit_code=result.exit_code,
    execution_output=result.output,
    base_files=base_files,
)
print(evidence.candidate_digest, evidence.changed_paths, evidence.test_passed)
```

`orchestrator.adapters.container.ApprovedContainerAdapter` wires steps 2-4
together automatically as part of the admission flow (token verification +
consumption, worktree snapshot, verification) — see
`tests/unit/test_approved_container_adapter.py` for a complete worked
example including a real git worktree.

## 7. Issue a merge approval token

If your task sets `approval.before_merge: true` (the template does), a
Human operator issues a single-use, HMAC-signed token before merge:

```bash
python -m orchestrator.cli approve \
  --action merge_pull_request \
  --repository YOUR_GITHUB_OWNER/YOUR_REPOSITORY \
  --task-id TASK-001 \
  --head-sha <commit-sha> \
  --target-ref refs/heads/main \
  --command "git merge task/task-001" \
  --policy-hash <sha256-of-policy> \
  --plan-hash <sha256-of-plan> \
  --approved-by <your-username> \
  --key-file /path/to/operator.key
```

The token is stored in the SQLite approvals ledger and is consumed exactly
once when the GitHub operation actually runs.

## 8. Open the PR

The Factory does not push branches or open PRs for you — that transport is
intentionally unimplemented (`GitHubStatePublisher.publish_branch` /
`create_or_update_pr` both raise `NotImplementedError`; see
[Safety Model](../README.md#safety-model)). Once validation and approval
have produced evidence you trust, push the branch and open the PR yourself
(`git push`, `gh pr create`, or your normal review workflow).

## What's next

- [Adapter Guide](adapters/README.md) — connect Claude Code, Codex, or your
  own agent instead of hand-editing the worktree in step 4.
- [Architecture](../ARCHITECTURE.md) — full component and state-machine spec.
- [Operations Guide](../OPERATIONS.md) — crash recovery, CLI reference, log
  locations.
- [Compatibility Matrix](compatibility/matrix.md) — what's verified where.
