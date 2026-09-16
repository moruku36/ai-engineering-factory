# 設計に影響した資料・参考文献

AI Engineering Factory は独立して開発しているプロジェクトです。以下の資料をそのまま設計図としてコピーしたわけではなく、公開されている考え方を設計上の参考材料として利用し、このFactoryに必要な最小構成へ落とし込んでいます。

特に重視しているのは、Safety、Reproducibility、Observability、Maintainability、Cost Efficiencyです。

## Anthropic

### 1. Building a C compiler with a team of parallel Claudes

Nicholas Carlini, 2026-02-05  
https://www.anthropic.com/engineering/building-c-compiler

**Factoryへの反映:**  
複数Agentによる並列処理は、作業が本当に分離可能な場合に有効であること、独立した作業環境によってAgent同士の干渉を抑えられること、役割を専門化することで品質向上が期待できることを参考にしています。

また、共通Git Repositoryへ成果物を残すことで、Agent間の調整状況を人間が追跡できる点も重要な参考になっています。

一方で、強く依存する作業へ複数Agentを投入しても効率が上がるとは限らないため、Factoryでも**Agent数を増やすこと自体を目的にせず、本当に独立したTaskだけを並列実行する**方針を採用しています。

### 2. How we built our multi-agent research system

Anthropic, 2025-06-13  
https://www.anthropic.com/engineering/multi-agent-research-system

**Factoryへの反映:**  
Lead / OrchestratorがTaskを分割し、専門化したSubagentへ委譲し、最後に結果を統合する **Orchestrator–Worker Pattern** を参考にしています。

Factoryでは、この考え方をDependency-aware Scheduler、Task Assignment、Builder / Tester / Reviewerという役割分離に反映しています。

Multi-Agent Systemは通常のSingle-Agent WorkflowよりToken Costが大きくなりやすいため、Factoryでも大規模Swarmを前提とせず、少数Agentを必要な箇所だけ使う設計にしています。

### 3. Effective harnesses for long-running agents

Anthropic, 2025-11-26  
https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents

**Factoryへの反映:**  
長時間・複数SessionにまたがるAgent作業では、ModelのContextだけに状態を保持するのではなく、外部に構造化Artifactを残す必要があるという考え方を参考にしています。

Factoryでは以下の情報をRepositoryや永続Stateに残します。

- Task / Feature List
- Progress Note
- Git Commit
- Validation Evidence
- Initialization State
- Handoff Record
- Known Issue

これにより、前のAgent Sessionが終了しても、次のAgentがGit上の情報を読み取って作業を再開できる構造を目指しています。

### 4. Harness design for long-running application development

Prithvi Rajasekaran, 2026-03-24  
https://www.anthropic.com/engineering/harness-design-long-running-apps

**Factoryへの反映:**  
Planner / Generator / Evaluatorの責務分離、独立した評価、段階的な成果物生成、明示的なAcceptance Criteriaといった考え方を参考にしています。

Factoryではおおむね次の役割に対応します。

```text
Planner / Architect
        ↓
Builder / Generator
        ↓
Tester / Reviewer / Evaluator
```

ただし、AgentやHarnessを追加するほど必ず性能が上がるわけではありません。そのため、FactoryではAgent追加によるWall-clock Time、Retry Rate、Cost、Human Review Timeなどを測定し、複雑化に見合う価値があるか確認することを重視しています。

### 5. Building effective agents

Anthropic, 2024-12-19  
https://www.anthropic.com/engineering/building-effective-agents

**Factoryへの反映:**  
巨大で不透明なAgent Frameworkを最初から導入するのではなく、単純で組み合わせ可能なWorkflowを使い、必要性が確認できた場合だけ複雑化するという思想を参考にしています。

このためFactory Coreは、Agent Frameworkそのものよりも以下を中心にしています。

- Git Repository
- YAML / JSON Schema
- Task Manifest
- State Machine
- Policy
- Validation
- Human Approval

Phase 1ではSingle Agentでも成立させ、後からMulti-Agent化、自動Orchestrationへ拡張するIncremental Architectureもこの考え方と整合しています。

### 6. Claude Code: Best practices for agentic coding

Anthropic, 2025-04-18  
https://www.anthropic.com/engineering/claude-code-best-practices

**Factoryへの反映:**  
Repository内にCommand、Test方法、Git Convention、Development Ruleなどを明示し、Agentが繰り返し同じルールを参照できる構造を参考にしています。

FactoryではClaude固有のInstruction Fileだけに依存せず、より一般化した形で以下に展開しています。

- `AGENTS.md`
- `.agents/rules/`
- `.agents/skills/`
- Task Manifest
- Hooks
- Validation Gate

独立したAgentによるReviewやTestも、必要な箇所で利用できる設計にしています。

## Google Antigravity

### 7. Teamwork: When AI Becomes a Research Partner

The Antigravity Team, 2026-08-27  
https://antigravity.google/blog/teamwork-when-ai-becomes-a-research-partner

**Factoryへの反映:**  
 loosely organized なAgent群より、構造化されたMulti-Agent Orchestrationが重要であること、難しいTaskでは明示的な以下のLoopが有効であるという考え方を参考にしています。

```text
Generate
  ↓
Critique
  ↓
Refine
  ↓
Verify
```

FactoryのOrchestrator / Builder / Tester / Reviewerという役割や、Validation後にHuman Merge Gateを置く構成は、この考え方と近いものです。

ただし、Agentの役割や数を固定するのではなく、問題の性質に応じて必要なAgentだけを利用することを前提にしています。

Antigravity Teamworkの現在のDocumentation:  
https://antigravity.google/docs/teamwork/

## 参考資料とFactory設計の対応

| Factoryの設計 | 参考にした考え方 |
|---|---|
| Orchestrator → Specialized Worker | Anthropic Multi-Agent Research / Google Antigravity Teamwork |
| 独立Taskだけを並列実行 | Parallel Claudes / Multi-Agent Research |
| Builder / Tester / Reviewerの分離 | Parallel Claudes / Planner-Generator-Evaluator Harness |
| Gitを利用したProject Memory / Handoff | Long-running Agent Harness / Agentic Coding Best Practices |
| Task Manifest / Validation / Promotion Criteria | Harness Design / Antigravity Teamwork |
| 小さくComposableなCore | Building Effective Agents |
| High-impact OperationへのHuman Approval | Factory固有のSafety Requirement + Human-controlled Orchestration |
| Agent追加前にCost / Throughputを測定 | Multi-Agent Token Cost / Harness Complexityに関する知見 |

## このFactoryでのアレンジ

AI Engineering Factoryでは、参考にしたシステムの規模をそのまま再現することは意図していません。

標準構成として想定しているのは、おおむね2〜3 Agent程度の小規模なTeamです。

```text
Orchestrator
   ├─ Builder
   ├─ Tester / Validator
   └─ Reviewer
```

Task Dependencyや共有Resourceの関係から並列実行が安全でない場合は、Agent数に関係なくSequential Executionを選択します。

また、FactoryではGit Repositoryと永続StateをPrimary Source of Truthとして扱います。

Model固有のMemory、Vendor固有のSession Persistence、Memory MCPなどのExternal Memory Serviceは将来的な拡張として利用できますが、Factory Coreの正しさがそれらに依存しないことを設計原則としています。
