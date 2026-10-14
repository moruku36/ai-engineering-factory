# GitInject: prompt injection in AI-powered CI/CD — research survey and proposals

[English](gitinject-2606.09935.md) | [日本語](gitinject-2606.09935.ja.md) · [README](../../README.md) · [Governance roadmap](../architecture/governance-roadmap.md)

*Research note on arXiv 2606.09935. The proposals below are our own, are **not implemented**, and are not product claims. The paper's attack inputs and commands are deliberately not reproduced. Assessment is textual only; no experiment, code run or reproduction was performed.*

## Source and status

**Paper:** GitInject: Real-World Prompt Injection Attacks in AI-Powered CI/CD Pipelines. **Authors:** Jafar Isbarov, Umid Suleymanov, Ilia Shumailov, Murat Kantarcioglu. **Version:** arXiv v1 (cs.CR), submitted 2026-06-07 19:17 UTC; checked 2026-10-14 UTC. We do not claim that no later version exists. Peer-review status is not confirmed; we treat it as a preprint. Its HTML carries a CC BY 4.0 notice.

**Links:** [abstract](https://arxiv.org/abs/2606.09935v1) · [HTML v1](https://arxiv.org/html/2606.09935v1) · [PDF](https://arxiv.org/pdf/2606.09935). We read the HTML in full: [§3](https://arxiv.org/html/2606.09935v1#S3), [§4](https://arxiv.org/html/2606.09935v1#S4), [§5.1–5.5](https://arxiv.org/html/2606.09935v1#S5), [§6.2](https://arxiv.org/html/2606.09935v1#S6.SS2), [Appendices A–H](https://arxiv.org/html/2606.09935v1#A1) and Tables 1–5. We did not cross-check the PDF or inspect the authors' released code. A fuller record, with numbers and unresolved text/table inconsistencies, is in the [independent survey note](https://github.com/moruku36/independent-cs-research-2026/blob/main/surveys/collection-v2/2026-gitinject.md) (available once merged).

## What the paper reports (paper's claims)

- Method: ephemeral GitHub repositories, target workflows deployed verbatim, attack input injected into the event, outcome checked through the GitHub API. The authors state that deterministic state checks are used for security and an LLM judge only for utility such as review quality ([§4](https://arxiv.org/html/2606.09935v1#S4), [App. E.1](https://arxiv.org/html/2606.09935v1#A5)). That is the authors' description of their method, not established practice, and it conflicts with Table 5, which labels the judgment/approval-manipulation attacks as LLM-evaluated (unresolved).
- Scope: four providers (Claude, Codex, Gemini, Cline), four representative workflows, eleven named attacks, each scenario run five times with identical results. This is **not** all current models or all configurations; failed cells do not show safety ([§6.2](https://arxiv.org/html/2606.09935v1#S6.SS2)).
- Central finding: a provider instruction file added on the PR branch is checked out and loaded as operator-level guidance, so low-trust input becomes trusted configuration ([§3](https://arxiv.org/html/2606.09935v1#S3), [§5.3](https://arxiv.org/html/2606.09935v1#S5.SS3)). A paired baseline suggests the trust escalation, not the wording, is what matters.
- Simulation gap (Table 1): over a 100-run confusion matrix (5 models × 10 tasks × 2 user tasks) AgentDojo had 23 TP, 1 FP, 57 FN, 19 TN against real execution. The 71.2% miss rate is 57 of 80 real successes; the 5.0% is 1 of 20 real failures. It is one benchmark and not a general statement about simulators.
- Availability: the denial_of_wallet scenario is listed as 5/5 confirmed in Table 5; only the **campaign amount and Actions minutes** ($32–$111, 400 minutes for a 2-hour, 100-PR campaign) are projections. Content-policy key suspension is a **hypothetical** that was not tested.

## Evidence limits and unresolved inconsistencies

The HTML has formatting damage (code blocks and math missing in places, colour coding lost) and several table/text mismatches, for example the LLM-judge statement versus Table 5 labels, Gemini PR-body results in Table 3 versus §5.2/Table 5, the denial-of-wallet per-PR cost arithmetic, and "eleven reproduced" versus one attack that failed. (Four evaluated workflows versus a 13-entry inventory is different coverage, not treated as a contradiction.) We do not resolve these by guessing; see the survey note for the list. Conclusions below rely only on points the text states consistently.

Paper mitigations have limits:

- `persist-credentials: false` removes one credential artifact. It is not a general proof; the paper says it does not cover other credentials.
- Restricting shell tools does not protect an agent's **judgment**; judgment manipulation uses no shell.
- Filtering by author trades protection against service to external contributors. Human approval is not a guarantee either ([App. D](https://arxiv.org/html/2606.09935v1#A4)).

## Existing overlap with this project

| Area | What exists (evidence) | Gap / limit |
|---|---|---|
| Execution boundary | [OfflineContainerRunner](../../orchestrator/core/container.py): offline Linux, registered argv, no host credential mounts, trusted cleanup. [CI](../../.github/workflows/ci.yml) uses `pull_request`, read-only `contents` permission and SHA-pinned actions. | No contract that separates trusted instruction/config provenance from the candidate. Linux only; this is not a check of third-party agent actions. |
| Complete candidate | Complete-diff handling is limited and handoff rejects such tasks (README). | Full-candidate and policy-hash binding is a G1 proposal. |
| Approval | [ApprovalManager](../../orchestrator/core/approval.py), single-use HMAC tokens. | Not bound to config provenance; hook support is not proof every entry point is gated. |
| Credentials | [Credential broker proposal](../security/local-credential-broker.md); synthetic in-process broker code; the Windows store and RunPod live paths are default off (not all synthetic broker code). | No deployed worker/broker isolation; synthetic tests do not prove live behaviour. |
| Evidence | COLLECTED-only receipts, [IndependentVerifier](../../orchestrator/core/verifier.py). | No policy that keeps security effects and LLM utility judgments separate or separate input/output/cumulative budget gates. |

AGENTS.md and the `.agents/` files describe roles and rules; they do not by themselves establish runtime enforcement. We do not claim this project is affected by, or protected against, the paper's attacks: it launches no AI worker and runs MANUAL_ONLY.

## Our proposals (project view; not implemented)

These adapt the paper's defensive lessons to the G1–G5 roadmap in the existing MANUAL_ONLY architecture. They are not endorsed by the paper's authors and add no deadlines.

1. **Trusted base for instructions.** Instruction and configuration files an agent obeys come from a pinned trusted base reference, never from the candidate checkout. A candidate may *propose* a change to them; the change is data for review, not authority. Records state the base reference and digest of each such file.
2. **Full-candidate and policy binding.** Evidence and approvals bind the complete candidate, the effective policy/config digest and the trusted instruction digest. Any change invalidates them (extends G1/G2).
3. **Runner credential surface.** Record, per run, which credentials, mounts, environment entries, writable paths and egress destinations the runner can reach, and minimize them. Treat an artifact the runner writes (such as a stored token file) as part of that surface. Non-listed surfaces are `unknown`, and unknown blocks admission.
4. **Advisory-only output.** An agent's output is a recommendation; it cannot approve, merge or change policy. Review verdicts from a model carry no authority by themselves.
5. **Independent security effects.** Security-relevant effects (credential reached output, scope violated, unexpected write) are checked by deterministic, independent checks of ground-truth state. An LLM judge may score utility only and is never used for a security decision. This is our proposal; the paper's own use of an LLM judge for judgment-manipulation outcomes (Table 5) shows why such outcomes need a separately specified check.
6. **Separate budget gates.** Input size is checked before the model call; the output cap is preconfigured before the call (actual output size cannot be known in advance); actual output and cumulative usage (per task, per principal, per period) are checked during and after the call. These are separate gates and exceeding any stops further work. A retry or restart cannot reset the cumulative gate.
7. **Fail closed.** A missing, unavailable or unparseable gate, provenance record or digest stops the run rather than falling back.

### Expected effects (hypotheses, untested)

Each is a hypothesis to test in the offline exercise, not a result: a trusted base should reduce instruction escalation from the candidate; digest binding should detect stale or tampered evidence; a minimal runner surface should reduce exfiltration opportunity; advisory-only output should limit an agent's authority; budget caps should limit cost.

### Adoption conditions

Proposal 1–2 only after the G1 complete-diff foundation is accepted. Proposal 3 only with an explicit data/credential inventory for the runner. Proposal 4 requires no code change to start as a documentation rule. Proposal 5–6 only with a defined, reviewed policy format. None changes permissions, credentials or workflows in this change.

### Minimal OFFLINE future proof of concept (proposed, not started)

A manual, offline, **inert contract/enforcement check**, not a test of a real model: it shows whether the proposed gates and provenance rules behave as specified, and does **not** demonstrate resistance to real model prompt injection. fake credentials (clearly marked synthetic markers), a local temporary repository, **no live workflow, no real service, no network, no real API key**. Compare, under identical inputs, (a) instruction file taken from the candidate, (b) the same file taken from the trusted base, and (c) the runner surface inventory with and without minimization. **Controls:** a *positive control* seeds a deliberately fake marker into a stand-in output; the detector must catch it, otherwise the detector is invalid and the run is void. A *negative control* is a clean, approved baseline that must pass with no finding. Security effects are measured only by deterministic checks of local state (marker appears or not in outputs, files, logs); a model is represented by fixed stand-in outputs, not a live call. Scenario inputs are inert descriptions agreed in review; no payloads from the paper are copied.

### Evaluation thresholds (proposed)

Report all trials and denominators. Proposed passing conditions: both controls behave as specified; zero synthetic markers in any output channel across all trials of the **protected arm** (the intentionally unsafe comparator is expected to show markers and is not held to this); every changed bound item (candidate, policy, instruction digest) rejected; every missing-provenance and gate-unavailable case blocked; budget gates (input check, preconfigured output cap, actual-output and cumulative checks) trip at the limit and survive restart. A pass is a contract/enforcement result for this bounded scenario, not evidence of resistance to real model injection.

### Risks and rejection conditions

Reject or revise if: the base/candidate split cannot be shown in the offline exercise; a trusted-base file can be altered by the candidate path; an LLM judgment is needed for any security decision; minimization breaks required utility without an accepted trade-off; budget gates need provider features that are unverified; or the work would need live credentials or workflows. Risks: false confidence from a synthetic result, duplicated control logic, and review burden. Judgment-manipulation attacks (misleading a reviewer) are not stopped by these controls alone and need advisory-only output and human review with its own limits.

[Roadmap supplement](../architecture/governance-roadmap.md#supplement-prompt-injection-in-ai-cicd-proposals-not-implemented)
