# Governance roadmap

*Proposal only. No deadlines and no automatic release. The current change implements only G0 (documentation and display name). G1-G5 are not implemented.*

## Source and status

Ideas are adapted from Shun Kimura, [AI Execution Accountability Framework — Discussion Draft](https://www.docswell.com/s/k1-c/Z9NDXY-2026-10-10-060401#p1) (cover dated 2026-09-14; published 2026-10-10). It is discussion material. It is not a certified standard, a normative product specification, a legal determination, or an endorsement by the author, and it does not certify this project. We summarize it in our own words and do not rely on its legal or external-reference claims, which we have not verified. **Our adaptation** (the stages below) is distinct from the draft's claims and is not the author's recommended code.

Ideas used: start from the action, then risk, needed knowledge and accountable people ([pp. 9-10](https://www.docswell.com/s/k1-c/Z9NDXY-2026-10-10-060401#p9)); separate actor, reviewer and owner as risk grows ([pp. 26-28](https://www.docswell.com/s/k1-c/Z9NDXY-2026-10-10-060401#p26)); the human roles (actor, reviewer, owner) are described on [pp. 26-28](https://www.docswell.com/s/k1-c/Z9NDXY-2026-10-10-060401#p26); connect policy to qualification, permission and evidence ([p. 31](https://www.docswell.com/s/k1-c/Z9NDXY-2026-10-10-060401#p31)).

## Current state (main `2525cbbdaf17947dcdd20943afb9098b8cb30c5e`)

Base: full pinned main SHA [`2525cbbdaf17947dcdd20943afb9098b8cb30c5e`](https://github.com/moruku36/ai-engineering-factory/tree/2525cbbdaf17947dcdd20943afb9098b8cb30c5e). For current project status see [PROJECT_STATE.md](../../PROJECT_STATE.md). For the approved-container adapter and its limits see [APPROVED_CONTAINER_LOOP.md](../operations/APPROVED_CONTAINER_LOOP.md).

Implemented: task JSON Schema, DAG, one risk enum (`low/medium/high/critical`), command/path policy, offline Linux containers, collection and IndependentVerifier (complete-diff limits remain), ApprovalManager with single-use HMAC tokens, ApproverRegistry identity/action permissions, authenticated CLI approve (`cmd_approve`), SQLite ledger/journal, GitHub checks, COLLECTED-only receipts, and default-off Windows/RunPod code. HMAC token integrity/single-use and ApproverRegistry identity/action permission are distinct mechanisms. Protected registry and key provisioning in a real deployment is still required. Status is Experimental/MANUAL_ONLY; evidence is synthetic/CI, not live keys, GPU, Windows Hello, or Mattermost.

AI Builder/Tester/Reviewer in AGENTS are engineering phases, separate from the draft's human Actor/Reviewer/Owner. Existing role/key authentication is not qualification or an automatic separation-of-duties guarantee. No unified risk-reason, accountability, or qualification admission contract exists.

## Proposed stages (not implemented)

**G0 — Naming and documents.** Display name, roadmap, ADR, stale-doc correction. Acceptance permits display-only updates to source strings and tests, but public identifiers and API behavior are preserved. Done when these documents merge and no code identifier or API behavior changes.

**G1 — Complete diff and assessment.** A complete-diff contract with negative tests for deletion, mode, rename and unknown base; receipt rejection stays until proven. Add a separately versioned governance assessment bound to task, candidate and policy, recording action, data, external impact, reversibility, reasons, unknowns and the human assessor. The existing risk enum stays; the draft's "Moderate" maps explicitly to `medium`, as a boundary and not a blanket replacement. `schema_version` 2020-12 is the JSON Schema draft, not a product contract version. Done when each negative case is rejected in tests and a tampered assessment is rejected.

**G2 — Accountable review and approval.** Human Actor/Reviewer/Owner roles; risk-based review and separation. Approval digest-binds assessment, review, candidate, inputs, command, destination and policy; expiry and revocation are rechecked before use; Python API and CLI share gates; hard denies cannot be overridden. Done when changing any bound item, or using an expired/revoked approver, blocks through both paths.

**G3 — Minimal qualification references.** Record issuer, method, scope, subject, issue time, expiry/revocation. No LMS; training or AI self-report is not competence; qualifications never grant credentials automatically; do not publish unnecessary private identity. Done when a missing, expired or out-of-scope reference fails review admission and changes no credential.

**G4 — Explainable reports and pilot.** JSON and human reports connect task, reason, review, approval, execution and PR, preserving unknowns and the COLLECTED/verified/completed distinctions; a hash alone is not authenticity. Run a small pilot measuring review time, retries and restore. Done when a report reconstructs one pilot run without hidden gaps and the measurements are recorded.

**G5 — One live adapter.** Only after prior gates, one bounded adapter at a time, based on actual official capability, with scope, budget, time, stopping, idempotent reconciliation of uncertain outcomes and real external cleanup. Credential and RunPod paths stay default off. No model proxy, new UI, auto-merge or production guarantees. Done when a rehearsal on the real service shows cleanup and reconciliation.

## Preconditions

Before any live stage, decide separately the owner, pilot, data, competence issuer and first adapter. No functions are added now.
