# Design influences and references

AI Engineering Factory is an independent implementation. The sources below are not copied as blueprints; they were used as design input and then reduced to the smallest patterns that fit this project's safety, reproducibility, observability, and cost goals.

## Anthropic

### 1. Building a C compiler with a team of parallel Claudes

Nicholas Carlini, 2026-02-05  
https://www.anthropic.com/engineering/building-c-compiler

**Relevant ideas used here:** parallel agents can be effective when work is genuinely separable; isolated working environments reduce interference; specialized roles can improve quality; shared Git artifacts make coordination inspectable. The article also reinforces a core Factory rule: do not parallelize tightly coupled work merely because more agents are available.

### 2. How we built our multi-agent research system

Anthropic, 2025-06-13  
https://www.anthropic.com/engineering/multi-agent-research-system

**Relevant ideas used here:** orchestrator-worker decomposition, specialized parallel subagents, explicit delegation boundaries, synthesis after independent work, and the need to account for the much higher token cost of multi-agent systems. This influenced the Factory's dependency-aware scheduler and its preference for a small number of workers rather than a large swarm.

### 3. Effective harnesses for long-running agents

Anthropic, 2025-11-26  
https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents

**Relevant ideas used here:** long-running work needs structured artifacts that survive context resets. Progress notes, feature/task lists, initialization state, test evidence, commits, and explicit handoff records map directly to the Factory's repository-backed memory and durable state model.

### 4. Harness design for long-running application development

Prithvi Rajasekaran, 2026-03-24  
https://www.anthropic.com/engineering/harness-design-long-running-apps

**Relevant ideas used here:** planner/generator/evaluator separation, independent evaluation, incremental delivery, and explicit criteria for judging generated work. It also supports the Factory's anti-goal of adding orchestration complexity unless the additional agents produce measurable value.

### 5. Building effective agents

Anthropic, 2024-12-19  
https://www.anthropic.com/engineering/building-effective-agents

**Relevant ideas used here:** prefer simple, composable workflows over opaque agent frameworks; distinguish predictable workflows from open-ended agents; add complexity only when it produces a demonstrated benefit. This is one reason the Factory core stays repository- and schema-centric instead of becoming a large agent platform.

### 6. Claude Code: Best practices for agentic coding

Anthropic, 2025-04-18  
https://www.anthropic.com/engineering/claude-code-best-practices

**Relevant ideas used here:** keep repository-local instructions for commands, tests, Git conventions, and development rules; use repeatable test/implementation loops; and use independent review where it adds value. The Factory generalizes that idea through `AGENTS.md`, `.agents/`, task manifests, hooks, and validation gates rather than depending on a Claude-specific instruction file.

## Google Antigravity

### 7. Teamwork: When AI Becomes a Research Partner

The Antigravity Team, 2026-08-27  
https://antigravity.google/blog/teamwork-when-ai-becomes-a-research-partner

**Relevant ideas used here:** structured multi-agent orchestration is more reliable than loosely organized agents; difficult work benefits from explicit generate → critique → refine → verify loops; agent roles and promotion criteria should depend on the problem; humans retain control of the objective and final acceptance. This maps closely to the Factory's Orchestrator / Builder / Tester / Reviewer roles and Human merge gate.

Current Teamwork product documentation:  
https://antigravity.google/docs/teamwork/

## How these references map to the Factory

| Factory design choice | External design influence |
|---|---|
| Orchestrator → specialized workers | Anthropic multi-agent research; Google Antigravity Teamwork |
| Parallelize only independent tasks | Parallel Claudes; multi-agent research cost/coordination findings |
| Builder / Tester / Reviewer separation | Parallel Claudes; planner/generator/evaluator harness |
| Git-backed project memory and handoff | Long-running agent harnesses; agentic coding best practices |
| Task manifests, explicit validation, promotion criteria | Harness design; Antigravity Teamwork |
| Small, composable core | Building effective agents |
| Human approval for high-impact actions | Factory-specific safety requirement, consistent with human-controlled orchestration patterns |
| Measure cost and throughput before adding agents | Multi-agent research token-cost findings; long-running harness complexity findings |

## Project-specific adaptation

The Factory deliberately does **not** reproduce the scale of the cited systems. Its default target is a small engineering team of roughly two to three active agents, with sequential execution whenever dependencies or shared resources make parallel execution unsafe or wasteful.

The repository and its durable state are treated as the primary source of truth. Model-private memory, vendor-specific session persistence, and external memory services can be useful extensions, but they are not required for correctness of the core workflow.
