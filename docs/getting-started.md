# Getting Started

This is the one-scenario walkthrough: install the Factory once, then use it
to run a task against **your own repository** end-to-end and see the
resulting evidence. It should take about 15 minutes.

If you want the "why" behind these steps, read the [README](../README.md)
first. This page is only the "how".

> **OS note**: full isolated execution (`OfflineContainerRunner`) requires a
> local Linux Docker daemon and is Linux-only today. Everything else in this
> walkthrough (CLI, `ManualAdapter`, verification, approval tokens) runs on
> Linux, Windows, and — expected but not CI-verified — macOS. See the
> [Compatibility Matrix](compatibility/matrix.md).

There are two separate directories in this walkthrough — don't confuse them:

- **The Factory itself** — this repository, cloned once. It gives you the
  `ai-factory` command.
- **Your repository** — the project you actually want to run tasks against.
  Everything from step 2 onward runs from *inside that repo*, not inside the
  Factory's clone.

## 1. Install the Factory

```bash
git clone https://github.com/moruku36/ai-engineering-factory.git
cd ai-engineering-factory

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -e ".[dev]"
```

This installs a console script, `ai-factory`, on your `PATH` (equivalent to
`python -m orchestrator.cli` run from inside this clone — either works from
here on, `ai-factory` is just shorter). Keep this directory around; you'll
copy one template file out of it in step 4.

## 2. Switch to your own repository

Everything from here runs from inside the repository you want to govern —
not from inside the Factory's clone:

```bash
cd /path/to/YOUR_REPOSITORY
```

## 3. Check your environment

```bash
ai-factory doctor
```

This checks Python, Git, GitHub branch protection for *your* repo (if `gh`
is authenticated; it auto-detects `owner/repo` from `git remote get-url
origin` in the current directory), and the Antigravity native-runtime
probe. A clean environment still exits with code `2` — that is expected,
not a failure. It means **Execution Mode: MANUAL_ONLY**: every merge
requires an explicit Human approval token, by design (see
[Safety Model](../README.md#safety-model)).

## 4. Point the Factory at your repository

Still inside your own repository:

```bash
ai-factory init --repository YOUR_GITHUB_OWNER/YOUR_REPOSITORY
```

`init` does three things, all scoped to *your* repository (the current
directory):

- Creates a **runtime root** outside any git working tree (default:
  `~/.ai-engineering-factory/runtime/<owner>__<repo>/`) — transient state
  (worktrees, leases, logs, SQLite DBs) is never committed to your repo.
  `init` refuses a `--runtime-root` that resolves inside a git repository.
- Writes a local config file at `.ai-factory/config.yaml` in your repo,
  recording the repository and runtime root.
- Adds `.ai-factory/` to your repo's `.git/info/exclude` (not its tracked
  `.gitignore` — this stays local to your clone and is never committed, and
  doesn't touch a file you didn't author).

## 5. Write a task

Copy the template out of the Factory clone into your own repository:

```bash
mkdir -p tasks
cp /path/to/ai-engineering-factory/tasks/templates/basic-task.yaml tasks/task-001.yaml
```

Edit `tasks/task-001.yaml` (now inside *your* repo):

- `repository`: the `https://github.com/...` URL for the repo you ran
  `init` against.
- `allowed_paths` / `prohibited_paths`: the narrowest set of paths this task
  is allowed to touch. This is enforced on the real isolation path (step 7);
  `demo` (step 6) only schema-validates the manifest, it does not enforce
  these paths — don't treat a passing `demo` run as proof a task respected
  them.
- `validation`: which command(s) must pass. `command_id` must be in the
  `PolicyEngine` allowed command registry (`pytest`, `ruff`, `python`,
  `python3`, `git`, `npm`, `node` — see `orchestrator/core/policy.py`), but
  `ai-factory demo` (step 6) currently only has a built-in `argv` for
  `pytest`, run as `python -m pytest -q` against your repo's normal test
  discovery; the others work on the real isolation path.
- `output_artifacts`: files the task must produce for a run to count as
  `SUCCESS`. `basic-task.yaml` leaves this `[]` on purpose — a fresh
  checkout of your repo won't have a pre-existing report file, so requiring
  one would make your very first `demo` run fail for no reason. Once you
  want to verify a command actually produced a specific file, see
  [`tasks/templates/example-artifact-task.yaml`](../tasks/templates/example-artifact-task.yaml)
  for a worked example (and make sure your validation command actually
  writes that file, e.g. `pytest --json-report --json-report-file=...`).

You do not need a real AI agent to try this: for the demo step below, the
"builder" work is just whatever is already on disk in the worktree you point
it at (e.g. an existing branch, or a worktree you edited by hand or with any
coding agent of your choice).

## 6. Run it end-to-end (local demo)

Still inside your own repository:

```bash
ai-factory demo --task-file tasks/task-001.yaml --worktree .
```

This first validates the task manifest against `task.schema.json`, then runs
it through `ManualAdapter`: executes the validation command as a real
subprocess (no `shell=True`, sandboxed environment, `PolicyEngine`-checked),
then hashes the declared `output_artifacts` to produce a result.

**This demo path is intentionally not isolated, and does not enforce
`allowed_paths`/`prohibited_paths`** — it runs directly against the
worktree you pass it, with no network/filesystem boundary, and its
`candidate_digest` is derived from the artifacts it measured but never
independently re-verified against `base_sha`. It exists to show the task →
validation → result shape quickly, not to produce Evidence-grade output. Do
not point it at untrusted code. For the real isolation + verification
boundary, see step 7.

You should see something like:

```text
=== Demo: task TASK-001 via ManualAdapter (worktree=/path/to/your/repo) ===
[*] Executing validation step: pytest
    -> PASS (exit=0)
=== Result: SUCCESS ===
  artifact: reports/task-001-report.json -> 3f9a...c1
```

## 7. The real isolation + verification path

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

## 8. Issue a merge approval token

If your task sets `approval.before_merge: true` (the template does), a
Human operator issues a single-use, HMAC-signed token before merge:

```bash
ai-factory approve \
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

## 9. Open the PR

The Factory does not push branches or open PRs for you — that transport is
intentionally unimplemented (`GitHubStatePublisher.publish_branch` /
`create_or_update_pr` both raise `NotImplementedError`; see
[Safety Model](../README.md#safety-model)). Once validation and approval
have produced evidence you trust, push the branch and open the PR yourself
(`git push`, `gh pr create`, or your normal review workflow).

## What's next

- [Adapter Guide](adapters/README.md) — connect Claude Code, Codex, or your
  own agent instead of hand-editing the worktree in step 5.
- [Architecture](../ARCHITECTURE.md) — full component and state-machine spec.
- [Operations Guide](../OPERATIONS.md) — crash recovery, CLI reference, log
  locations.
- [Compatibility Matrix](compatibility/matrix.md) — what's verified where.
