# ADR 0004: Product name and governance roadmap

- Status: accepted
- Date: 2026-10-11

## Context

The project was named AI Engineering Factory. Its actual role is a control plane for tasks, verification, and human approval of edits made by people or external agents. It is not an LLM gateway and does not proxy model traffic. The old name suggested autonomous code production, which the project does not do. The owner chose a new display name.

A discussion draft, [AI Execution Accountability Framework — Discussion Draft](https://www.docswell.com/s/k1-c/Z9NDXY-2026-10-10-060401#p1) by Shun Kimura (cover dated 2026-09-14, published 2026-10-10), motivated a roadmap. It is discussion material. It is not a certified standard, a normative specification, a legal determination, or an endorsement, and it does not certify this project.

## Decision

1. The display name is **AI Governance Control** (formerly AI Engineering Factory). The name describes a governance control plane, not an LLM gateway.
2. The change is display-only. These identifiers stay unchanged for compatibility:
   - repository slug `moruku36/ai-engineering-factory` and distribution name `ai-engineering-factory`
   - import package `orchestrator` and CLI `ai-factory`
   - `AI_FACTORY_*` environment variables
   - `.ai-factory` and `.ai-engineering-factory` paths
   - credential target `AIEngineeringFactory`
   - schema IDs, repository/approval binding IDs, and API/class names
3. Any future identity migration is a separate, reviewed scope with its own migration and compatibility plan.
4. The owner permits G0 documentation and branding only. G0 acceptance allows display-only updates to source strings and tests, while public IDs and API behavior are preserved. G1 and later stages in [the governance roadmap](../architecture/governance-roadmap.md) ([日本語](../architecture/governance-roadmap.ja.md)) are proposals: not implemented, no deadlines, no automatic release.

## Consequences

- READMEs, the roadmap, and operations documents use the new display name; existing installs, scripts, and approvals keep working.
- The old name appears once in each README for discoverability.
- Changing bound identifiers would invalidate existing approvals and bindings, so they are deliberately excluded.
- Before any live stage, the owner, pilot, data, competence issuer, and first adapter must be decided separately.
- The roadmap is our adaptation of the draft's ideas, distinct from the draft's own claims, and is not the author's recommendation or endorsement.
