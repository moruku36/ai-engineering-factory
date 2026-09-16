# Offline Linux container boundary

This is the first implementation step after the PR #7 review. Overall readiness
remains **MANUAL_ONLY**. The [approved offline adapter](APPROVED_CONTAINER_LOOP.md)
now connects it to a single-worker run loop. Native execution and authenticated
approval issuance remain blocked.

## Scope

`orchestrator.core.container.OfflineContainerRunner` executes exact, immutable
`ContainerCommand` argv registered by the trusted controller. Task input cannot
select extra Docker flags, executables, network access or host mounts.

- Local Linux Docker socket only; no inherited Docker context or host environment.
- Provisioned local image ID (`sha256:...`), `--pull=never`, Linux/seccomp required.
  Images with implicit volumes are refused. Operators must trust the image and
  ensure it contains no embedded credentials; this is not a vulnerability audit.
- Non-root UID 65534, no capabilities, no-new-privileges, default seccomp, private
  IPC/cgroup namespaces, no network, read-only root, memory/CPU/PID limits.
- Read-only `/inputs` contains only explicitly supplied bytes: up to 100 flat files
  and 1 MiB. No repository, home, Git metadata, control database, approval key or
  Docker socket is mounted. Do not include secrets in those bytes.
- `/workspace` and `/tmp` are bounded disposable tmpfs. No host artifacts are exported.
  Results contain exit code and capped rotating Docker logs (last 1000 lines).
- Persistent intent journal precedes create. Removal requires full container ID,
  generated name and matching ownership labels. Cleanup is confirmed before returning.
  Timeout/transport/cleanup failures raise; there is no host-process fallback.
- After a controller crash, `reconcile(run_id)` on a fresh runner removes the owned
  container and snapshot. This is explicit operator recovery, not a background
  supervisor. If create timed out and no container is visible, the outcome remains
  uncertain and the journal is retained.

Serialize operator recovery for a given run; do not reconcile it concurrently with
normal execution. A recovered container ID is persisted before removal so cleanup
can be repeated after another controller crash.

Control root must be controller-owned mode 0700 outside the source repository.
Journals must remain inaccessible to workers. Docker administrators and the kernel
are trusted; a shared-kernel container is not a VM boundary. Windows Docker Desktop,
macOS, remote daemons and rootless sockets are unsupported by this profile.

## Control-plane API

The controller provisions an image separately, registers a command, then calls
`run(command_id, {"probe.py": b"..."})`. `ContainerResult` contains `run_id`,
`exit_code`, `output`; nonzero exit remains failure. Journal `cleanup=CONFIRMED`
means removal, not task acceptance. Exit code alone must not advance a task beyond
validation or grant Human approval.

Production image changes, network access, worktree mounts and native Agent admission
require separately reviewed profiles. Runtime execution never pulls an image.

## Verification

Unit regressions cover absent Docker, mutable images, traversal, host environment,
foreign ownership, uncertain create and cleanup failure. Dedicated Linux Docker CI
uses a fixed official Python image digest and verifies actual containers:

1. Host/control fixture invisibility, read-only input/root, writable scratch,
   absent inherited approval keys and blocked outbound network.
2. Timeout removes the container with a long-lived child process.
3. Concurrent workers have independent scratch files.
4. A killed controller's worker is removed by a fresh controller from its journal.
5. A failed command retains its nonzero exit code and stderr output.

The ordinary Linux/Windows suite explicitly skips these Docker tests. Only the
dedicated required-image job establishes real isolation evidence, not mocked calls.
Docker semantics: [Running containers](https://docs.docker.com/engine/containers/run/).

## Remaining work

Authenticated approval/protected keys; general concurrent admission; automatic crash/lease
reconciliation; verified artifact import; native Antigravity transport; controlled
model API networking; end-to-end acceptance and branch protection. AC-H01/H02 stay
partial until the worker lifecycle is connected to these controls.
