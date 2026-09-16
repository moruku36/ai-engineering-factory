# PR #7 completion assessment

Reviewed base: `2c6b1c5ba087dd57e62173e593efb8c9bfda4b5f` (2026-09-16).
Subsequent main updates through `167a454` were merged during review, retaining
the Japanese documentation, architecture diagrams and generic CLI repository detection.
Verdict: **not complete; MANUAL_ONLY**. Component additions do not satisfy real
isolation, authenticated Human approval, native execution or acceptance criteria.

## Findings and repairs

|Priority|Finding at reviewed base|Repair / remaining boundary|
|---|---|---|
|P1|Native adapter only added an in-memory record; collect returned SUCCESS without executing anything|Refuse unsupported start/results; remove fabricated version and auto-to-manual fallback|
|P1|Run loop invented preflight, validation and independent review, then marked DAG DONE before Human merge|Require existing READY, stop completion at VALIDATING, keep dependencies waiting; use the actual ExecutionAdapter methods|
|P1|HMAC had a source-code default key; CLI accepted a caller-supplied Human name|No default key; require provisioned key, canonical JSON signing; block unauthenticated CLI approval|
|P1|terminate_tree did not invoke its ownership validator|Reject foreign records at destructive entrypoint; fix Windows handle declarations and process identity parsing|
|P1|Publisher trusted any origin push URL and qualified branch refs bypassed main policy|Verify single approved push destination; reject ambiguous/qualified refs; push exact verified SHA and verify that destination|
|P1|Failed/malformed PR lookup could create another PR; closed PRs and unverified creation output counted as success|Fail closed on lookup errors; validate actual open PR number/URL/head; re-query after create|
|P1|CLI cancel changed RUNNING state without stopping its worker|Refuse running cancellation pending controller reconciliation|
|P2|Port reservation immediately closed its socket|Return a live, context-managed socket reservation; worker socket handoff remains to be integrated|
|P1|Secret scan fixture substring exempted an entire line; net diff missed historical/tree leaks|Remove broad exception; inspect intermediate commit patches and tracked HEAD tree; fail on tree-scan errors|

Existing signing records use the old signature format. They must be reissued by a
future trusted Human channel; do not add fallback verification using the old public
default key. Test fixtures use random per-test keys inherited by spawned test processes.
The approval library is an integrity primitive, not an authenticated approval service.

## Reproduced isolation gap

A local Windows probe launched a worker via ProcessTreeController in a dedicated
worker directory. The worker successfully read a harmless review-owned file in its
parent directory and exited 0. No real credentials or personal files were accessed.
This proves that current path helpers do not restrict worker filesystem access.
The controller also does not enforce the network_profile string. No sandbox was
installed or host identity changed during review.

## Acceptance re-evaluation

|AC|Status|Evidence boundary / remaining work|
|---|---|---|
|AC-H01|FAIL|No restricted identity/container/VM; outside-worker fixture read succeeded|
|AC-H02|PARTIAL|Ownership protection and live socket reservation repaired; full descendant lifecycle, owner cleanup and restart semantics still need real profile tests|
|AC-H03|PARTIAL|Transactional consume/HMAC primitives exist; no authenticated Human issuance or worker-inaccessible key/storage|
|AC-H04|PARTIAL|SQLite CAS exists; active sessions are in memory, restart reconciliation/journal and cancellation recovery incomplete|
|AC-H05|FAIL|Manual results still contain placeholder hashes; independent evidence verifier and real-candidate review pipeline missing|
|AC-H06|PARTIAL|Scan improved; dependency script only runs pip check, not CVE audit; no run/resume/validate CLI; approve intentionally blocked|
|AC-H07|BLOCKED|Native task transport/session/auth protocol not implemented; binary detection is not execution evidence|
|AC-H08|PARTIAL|git/gh transport exists with new destination checks; tests mock subprocess, no native acceptance or persistent mutation reconciliation|
|AC-H09|BLOCKED|No real Agent task→verified PR→Human merge→observed DONE trace|
|AC-H10|BLOCKED|No two real isolated workers or crash-injected concurrent workload trace|
|AC-H11|PARTIAL|115 tests pass on each Linux/Windows CI job at repair head dc9901635b27d45d0d7f66b04dc3f19ce5e853a8; real native/isolation acceptance remains blocked|
|AC-H12|BLOCKED|main protected=false at review; no authenticated/isolated operational boundary|

The old handoff lists mocked adapter calls as real verification and labels missing
remote protection PASS. Those claims are withdrawn; preserve the file as history.

Validation: [CI run 35069179363](https://github.com/moruku36/ai-engineering-factory/actions/runs/35069179363)
passed Ruff, secret scanning, dependency consistency and all 115 tests on both OSes.
The dependency gate is not a vulnerability audit. The main branch still reported
`protected: false` after the public-documentation merge. Local compileall passed;
local full pytest was unavailable because dependency downloads failed with TLS errors.

## Remaining implementation sequence

1. Build one real restricted worker profile and trusted control identity; prove
   file/network/control-key denial before enabling any native worker execution.
2. Integrate authenticated Human approval, persistent session/operation reconciliation,
   real commit/artifact provenance, and independent validation/review into the loop.
3. Implement the documented vendor SDK/CLI transport with real authentication,
   supported start/poll/cancel/collect and timeout reconciliation. Do not invent a
   protocol for an installed language-server executable.
4. Finish durable GitHub idempotency, real head/base/check/merge verification and a
   vulnerability audit. Resolve repo protection with the owner; do not change
   billing or visibility automatically.
5. In an explicitly approved disposable repository, perform one real task and
   Human merge, then two isolated concurrent tasks with crash/cancel injection.

This patch repairs dangerous false-success paths. It does not claim to implement the
missing OS sandbox, Human authentication service or native Antigravity protocol.
