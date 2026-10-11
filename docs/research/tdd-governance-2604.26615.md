# TDD governance for multi-agent code generation: research survey

[English](tdd-governance-2604.26615.md) | [日本語](tdd-governance-2604.26615.ja.md) · [README](../../README.md) · [Governance roadmap](../architecture/governance-roadmap.md)

*Research note on arXiv 2604.26615. The proposed TDD additions described here are not implemented, and none of them is a product claim. Assessment is textual only.*

## Source and status

**Paper:** TDD Governance for Multi-Agent Code Generation via Prompt Engineering. **Authors:** Tarlan Hasanli, Shahbaz Siddeeq, Bishwash Khanal, Pyry Kotilainen, Tommi Mikkonen, Pekka Abrahamsson.

**Version:** arXiv v1, submitted 2026-04-29 12:43:22 UTC, 5 pages. As of 2026-10-11 UTC, v1 is the version we checked. We do not claim that no later version exists or will exist. The paper says it was submitted to PROMPT-SE 2026. We could not confirm peer review or acceptance, and the manuscript still has DOI/ISBN placeholders. We therefore treat it as a preprint whose review status is unconfirmed.

**Links:** [abstract](https://arxiv.org/abs/2604.26615) · [HTML v1](https://arxiv.org/html/2604.26615v1) · [PDF v1](https://arxiv.org/pdf/2604.26615v1). We read the HTML sections [3.1](https://arxiv.org/html/2604.26615v1#S3.SS1), [3.2](https://arxiv.org/html/2604.26615v1#S3.SS2) and [4](https://arxiv.org/html/2604.26615v1#S4) most closely. The linked [manifesto JSON](https://github.com/shahbazsiddeeq/TDD-manifesto/blob/1c814b145d400e7c045089252ba65dd69eaf839f/tdd_principles_manifesto.json) is pinned to a commit.

## What the paper proposes (paper's claims)

The authors manually extracted a bounded set of normative TDD principles from Beck and Martin, turned them into a manifesto, and described a staged architecture (Sections 3.1 and 3.2). This was not a systematic literature review. In the design, the model only proposes structured changes, while an engine controls schema, policy and phase validation, and applies the changes. The intended flow is a failing test first (RED), a bounded repair loop toward passing (GREEN), then refactor checks.

## What the paper does not show (evidence limits)

Section 4 itself says most constraints are prompt-level, with only partial runtime verification. Semantic compliance and wider cross-model and cross-repository evaluation are left as future work. The paper does not report the models used, a dataset, task or trial counts, baseline conditions, outcome tables or statistics. It mentions initial experimentation only qualitatively.

The pinned manifesto tree contains only a README and the JSON. Its enforcement hints are not executable validators, and it provides no engine or experiment logs that would let a reader reproduce results. We make no claim about whether the authors' implementation exists elsewhere.

## Evidence box: easy-to-misread items

| Item | What it is | What it is not |
| --- | --- | --- |
| N=3 | A design repair budget | An evaluation sample size or a proven optimal value |
| 75.76% | A figure cited from a prior study | This system's measured improvement |
| Nano Banana Pro | Acknowledged for generating Figure 1 | A model used to evaluate code |
| 34 principles | Entries in manifesto v1.0.0 (last updated 2026-02-17) | 34 experimental tasks |

## Our critique (project view, not the authors' findings)

- Prompt discipline does not revoke a permission. A trusted engine that enforces a denial does. Prompt-level rules can still guide behavior, but they are not a substitute for enforced denial.
- Independent execution is not an independent oracle. Rerunning tests separately says nothing about where the approved specification and expected results came from. Record that source as well as the actor who ran the tests. A weak test run many times still does not prove the requirements.
- Giving one model several named roles does not remove correlated error. The word Independent in a role or tool name, including FIRST's Independent property, is not evidence of role or oracle separation.
- Passing tests shows only the inspected behaviors. It does not show full requirement coverage, absence of vulnerabilities, production safety, or authorization to execute, publish or merge.
- Deterministic checks do not establish identical generation or reproducibility across environments. A bounded stop does not guarantee convergence.
- A legitimate RED can be a missing intended API or a compile failure, if tied to an expected requirement. A dependency or runner outage alone is not an intended behavioral RED. We do not ban compile-failure RED.
- Many unknowns remain, and we keep them open.

## Roadmap stages: G0 complete, G1-G5 proposed (not implemented)

G0 is complete. G1-G5 are FUTURE-ONLY proposals. The TDD additions are opt-in, have no dates, and supplement existing stages. The [roadmap supplement](../architecture/governance-roadmap.md) keeps the short acceptance conditions. The details below are planning notes, not commitments.

### G1: evidence contract

After the complete-diff contract, add an opt-in, separately versioned TDD micro-cycle evidence contract. It is separate from task phase/status and uses the same engine. It would record:

- task and cycle ID, requirement and acceptance IDs with the approved version;
- base, full candidate and suite digests;
- test selection, test IDs and the requirement mapping;
- the expected RED reason;
- runner, command, config, dependency and policy provenance;
- measured run IDs and outcomes, and stop or exception reasons.

It would check that a known base failure is followed by a candidate pass against the same approved criteria. This covers part of order and correspondence, not semantic completeness. Applicability, non-applicability and exceptions (docs-only, refactor, legacy) must be declared. They must not fabricate a RED or silently waive required evidence.

Negative acceptance cases include: missing RED, different base, different suite, stale candidate, undiscovered tests, all-skipped runs, and runner failure treated as success. They sit alongside the existing complete-diff cases: deletion, mode change, rename and unknown base.

### G2: preserving approved criteria

Preservation covers fixtures, snapshots, expected values, skip and xfail markers, test discovery, conftest, plugins, dependencies, command arguments, thresholds and generated evaluation data. Approved criteria are read-only during GREEN and repair.

A legitimate change needs a reason, human review, a new version, reapproval and revalidation. It invalidates the affected RED, GREEN, review and approval records. A specification conflict goes to an accountable human. Test generator, oracle source, executor and approval authority should be separate roles. Optional mutation or property checks help but are not a complete oracle. The engine should reject swaps, deletes, renames, shrunk selection, all-skip runs and stale reuse.

### G3

- **G3:** unchanged. Test quality and human qualification stay separate.

### G4: pilot

A pilot with four arms: existing workflow, prompt only, engine evidence only, and both. All arms share the same security boundary. If resources permit only a comparison of the existing workflow with both additions together, the contributions cannot be separated. Requirements, oracle and evaluation are common and independent of the arms. Fix and report the exact model version, prompts, task-type counts, repetitions, token, time and cost budgets, and environment.

Metrics:

- independent satisfaction, residual defects, wrong mapping;
- violation and weakening attempts, rejections, misses, false blocks;
- repairs, repeated failures, no-ops, failures, BLOCKED outcomes, human interventions;
- review time, runtime, token cost, flakiness, rerun variation;
- restore and cleanup, and evidence reconstructability.

Report all trials, denominators, failures, unknowns and uncertainty. More stopping is not the same as fewer defects. Pass rate of generated suites alone is not the outcome. No productivity claim before data.

### G5: repair ledger

Only after the earlier gates, consider a trusted, durable, cumulative ledger of attempts, time and cost. It would also hold a normalized failure signature, patch digest, effective change and stop reason. Existing `max_attempts` 3 is not a new duplicated budget and not a proven optimum. A restart or new task cannot implicitly reset budget or approval.

Stops cover scope violations, unknowns, repeats, no-ops and budget exhaustion. Semantic patch equivalence stays advisory until it is defined and verified, and it is not an LLM hard gate. An uncertain external result is reconciled before any retry. Acceptance would check restart budget retention, scope and approval alignment, and no double execution. Any adapter would come only after the prior gates, and there is no immediate autonomous repair.

## Relation to current code

At pinned main [`8ef30734`](https://github.com/moruku36/ai-engineering-factory/tree/8ef30734d041c7fa817c7dc5d4209fa2d31c8a8d), G0 is merged (PR #37), G1-G5 are unimplemented, and status is Experimental/MANUAL_ONLY. Current state: [PROJECT_STATE.md](../../PROJECT_STATE.md).

- The [task schema](../../schemas/task.schema.json) phase enum (1-4) and phase contract are not TDD cycles or semantic verification. `retry.max_attempts` (maximum 3) exists but is not a proven durable TDD repair budget.
- [IndependentVerifier](../../orchestrator/core/verifier.py) candidate and JUnit checks do not prove a complete diff or TDD chronology. Diff handling centers on additions and changes; deletion, mode, rename and unknown base remain G1 work. Handoff rejects tasks that need a complete diff, and the adapter does not redispatch automatically. See [APPROVED_CONTAINER_LOOP.md](../operations/APPROVED_CONTAINER_LOOP.md). Pinned sources: [schema](https://github.com/moruku36/ai-engineering-factory/blob/8ef30734d041c7fa817c7dc5d4209fa2d31c8a8d/schemas/task.schema.json), [verifier](https://github.com/moruku36/ai-engineering-factory/blob/8ef30734d041c7fa817c7dc5d4209fa2d31c8a8d/orchestrator/core/verifier.py).

All current security boundaries, default-off and live-use limits, and public identifiers stay unchanged.

## Limits of this survey

This is a textual source assessment. We did not rerun the authors' engine, run project experiments, or validate a live adapter. CI may run later on the documentation PR, but CI results are not TDD experimental evidence.
