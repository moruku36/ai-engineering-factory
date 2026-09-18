# Case Study: Web Security Control Lab で見えた AI 開発ガバナンスの境界

この文書は、[Web Security Control Lab](https://github.com/moruku36/web-security-control-lab) を実際の対象リポジトリとして使い、複数のAI Coding Agentと AI Engineering Factory を組み合わせたときに何が起きたか、その失敗と改善を記録した実戦Case Studyです。

目的は「AIでうまく開発できた」という成功例を示すことではありません。むしろ、**自然言語の指示・allowed_paths・PR運用だけでは防げなかった境界違反を観測し、その結果をFactoryの機械的な制御へ還元した過程**を残すことです。

> このCase Studyは2026年9月時点の実装・運用に基づきます。Factoryは現在も Experimental / MANUAL_ONLY です。

---

## 1. 対象プロジェクト

対象は、FastAPI + SQLiteで構成したローカル専用の小型Web Security Labです。

- Repository: [moruku36/web-security-control-lab](https://github.com/moruku36/web-security-control-lab)
- 学習フロー: VULNERABLE → 検出 → 分析 → 修正 → 再検証
- Intentional findings:
  - LAB-01 Broken Access Control — HIGH
  - LAB-02 Missing HttpOnly — MEDIUM
  - LAB-03 Missing / Weak SameSite — MEDIUM
  - LAB-04 Missing Security Headers — MEDIUM
  - LAB-05 Information Disclosure — LOW
  - LAB-06 Authentication Logging Failure — MEDIUM

VULNERABLEモードの期待値は次のとおりです。

~~~text
HIGH:   1
MEDIUM: 4
LOW:    1
~~~

HARDENEDモードでは、同じローカルスキャナでFinding 0件を目標にします。

---

## 2. 当初想定していたAgent分担

当初の設計では、Agentごとの役割を明確に分離するつもりでした。

~~~text
Antigravity
Initial Builder
    ↓
VULNERABLE implementation
    ↓
STOP
    ↓
Factory Verification
    ↓
Claude Code / Sonnet
Independent Security Remediation
    ↓
Factory Verification
    ↓
Human Approval
    ↓
Merge
~~~

役割分担の意図は単純です。

- **Initial Builder** は脆弱状態と検出基盤までを作る。
- **Independent Reviewer / Remediation Agent** は、その後のフェーズでセキュリティ改修を行う。
- **Factory** は両者の自己申告を信用せず、差分・テスト・証跡・承認境界を検証する。
- **Human** は最終判断とMergeを担当する。

この分離が守られれば、「作ったAgent自身が自分の成果を採点する」構造を避けられます。

---

## 3. 実際に起きたこと: Phase Boundaryの先取り

Initial Builderは、要求されたVULNERABLE状態だけでなく、同じコード内にHARDENED側の実装も先に入れていました。

つまり実際には、

~~~text
Phase 1:
VULNERABLE implementation
+
future HARDENED implementation
~~~

となりました。

この結果、後工程のSonnetによるWSCL-003は「セキュリティ改修を新規実装する」よりも、**既存HARDENED実装の確認とテスト強化**が中心になりました。

実際の [web-security-control-lab PR #1](https://github.com/moruku36/web-security-control-lab/pull/1) では、変更対象は主にテストで、HARDENED / VULNERABLE双方の期待値をより明示的に検証する形になりました。

### なぜ既存の制御で防げなかったのか

当時のFactory Taskは、主に次のような空間的境界を持っていました。

~~~yaml
allowed_paths:
  - app/
  - tests/

prohibited_paths:
  - scanner/
  - factory/
  - .github/
~~~

これは「どのファイルを触れるか」は制約できますが、**そのファイル内で、どのフェーズの成果物まで実装してよいか**は表現できません。

app/ がPhase 1とPhase 3の両方で変更対象なら、Initial Builderが将来フェーズのコードまで実装しても、path boundary上は合法です。

ここで得られた重要な知見は次です。

> **Path BoundaryとPhase Boundaryは別物である。**

---

## 4. 2つ目の問題: PRがHuman Boundaryを越えた

もう1つの問題はMerge Boundaryでした。

Sonnet側には「PRを作成したら停止し、Mergeしない」という自然言語の指示を与えていました。しかし実験中、対象PRはFactoryの意図した最終検証・Human Approvalステップより先にMergeされました。

この時点で分かったことは、より根本的です。

> **「AgentにMergeしないよう指示する」ことは、Mergeを禁止することではない。**

さらに、AgentとHumanが同じ gh 認証情報を共有している場合、GitHubから見れば同じIdentityです。GitHub Rulesetだけで「これはHumanが押したMerge」「これはAgentが実行した gh pr merge」と区別することはできません。

そのため、Promptだけでなく次の境界が必要になりました。

~~~text
Worker / Coding Agent
    ↓
Independent Verifier
    ↓
PR
    ↓
Human Authorization
    ↓
Merge
~~~

---

## 5. 実験からFactoryへ還元した変更

この実験結果をAI Engineering Factory自身へフィードバックし、[PR #25](https://github.com/moruku36/ai-engineering-factory/pull/25) で制御を強化しました。

### 5.1 Machine-readable Phase Contract

Task Manifestに phase_contract を追加し、フェーズ終了時の状態を機械的に表現できるようにしました。

概念例:

~~~yaml
phase_contract:
  target_phase: 1

  preserves:
    - id: PRSV-01
      statement: "Intentional vulnerable behavior must remain"
      check_type: required_pattern
      patterns:
        - "VULNERABLE"

  prohibits:
    - id: PROH-01
      statement: "Future security remediation must not be introduced in Phase 1"
      target_phase: 3
      check_type: forbidden_pattern
      patterns:
        - "HARDENED"
        - "HttpOnly=True"
~~~

現在の実装では、Schema-validに見えるだけのno-op ruleを防ぐため、

- check_type 必須
- patterns 必須
- patterns.minItems = 1
- 空文字pattern禁止

を強制しています。

Unsupported / unimplemented check typeはsilent passせず、Fail-Closedで拒否します。

### 5.2 DiffとCandidate Stateの意味を分離

Phase Contractでは、検査対象の意味も分離しました。

- **prohibits**: base → candidate の差分に「今回新しく導入された後続フェーズ成果物」がないかを見る。
- **preserves**: 最終Candidate State全体で、維持すべき不変条件が残っているかを見る。

これにより、

- 以前から存在する文字列を無関係な変更で誤検知する
- 未変更ファイルに存在する重要なInvariantを見落とす

といった問題を減らしています。

### 5.3 PR HEADへのHuman Approval Binding

Human Approval Tokenは base_sha ではなく、**人間が実際にレビューするPR HEAD SHA** にbindされるように変更しました。

~~~text
base_sha
    ≠
PR head SHA
    ≠
merge commit SHA
~~~

これらは異なる意味を持ちます。

Human Approval後に新しいcommitがPRへpushされれば、

~~~text
approved_head_sha != current_pr_head_sha
~~~

となり、旧ApprovalではDONEへ進めません。

### 5.4 Human Merge VerificationをFail-Closed化

Security-sensitiveな verify_human_merge() では、Approval検証をcallerが無効化できるoptional flagを廃止しました。

さらに、

- approval token必須
- task_id 必須
- policy_hash 必須
- plan_hash 必須
- PR HEAD一致必須
- mergedBy 欠落 / 空 / malformed は拒否
- bot actorは拒否

とし、単なるread-only確認は get_pr_merge_status() に分離しています。

---

## 6. GitHub RulesetはDefense-in-Depth

Web Security Control Lab側では、mainに対してGitHub Rulesetも導入しました。

主な設定:

- Pull Request必須
- direct push禁止
- force push禁止
- branch deletion禁止
- CI success必須
- conversation resolution必須
- auto merge無効
- bypass actorなし

ただし、個人Repositoryかつ同一IdentityをAI/Humanで共有する構成では、RulesetだけでHumanとAgentを識別できません。

そのためFactoryでは、Rulesetを**最終的なHuman Identity保証ではなくDefense-in-Depth**として扱います。

より強い分離が必要なら、

~~~text
Worker Credential
- task branch push
- PR creation
- merge authorityなし

Human Credential
- review
- approval
- merge
~~~

というCredential Separationが必要です。

---

## 7. 検証結果

Web Security Control Labでは、最終的に以下を確認しました。

~~~text
VULNERABLE scanner:
HIGH:   1
MEDIUM: 4
LOW:    1

HARDENED scanner:
HIGH:   0
MEDIUM: 0
LOW:    0

pytest:
21 passed

ruff:
PASS
~~~

Factory側の改善PR #25では、Phase Boundary / Approval Boundary / Merge Boundaryに対する回帰テストを追加し、Linux / Windows / real offline container boundaryのCIを通過させました。

最終工程では、AI側はPR更新までで停止し、**Human OperatorがPR #25を手動Merge**しました。

これにより、少なくともこの実験では、

~~~text
AI implements
    ↓
AI / independent review
    ↓
machine verification
    ↓
PR
    ↓
AI stops
    ↓
Human merges
~~~

という境界を実運用でも確認できました。

---

## 8. この実験から得た設計原則

### 8.1 PromptはPolicyではない

「ここまでやって停止して」「Mergeしないで」とPromptに書くことは重要ですが、それだけではSecurity Boundaryになりません。

重要な境界は、

- Schema
- PolicyEngine
- IndependentVerifier
- State machine
- Approval Token
- GitHub Ruleset
- Credential separation

など、Agent自身が変更・迂回しにくい層へ移す必要があります。

### 8.2 allowed_pathsだけでは責務分離できない

Spatial Boundaryは必要ですが不十分です。

~~~text
Where can the agent write?
~~~

だけでなく、

~~~text
What state is this phase allowed to produce?
~~~

を検証する必要があります。

### 8.3 Independent Reviewerは「予定どおりの作業」をしなくてもよい

Sonnetが想定していたセキュリティ改修を大量に書かなかったこと自体は失敗ではありません。

既にHARDENED実装が存在することを発見し、テストの不足を補ったことは、独立Reviewerとして合理的な挙動でした。

問題は、**なぜHARDENED実装が前フェーズに存在できたのか**であり、そこでPhase Contractの必要性が明確になりました。

### 8.4 EvidenceはAgentの自己申告から分離する

「テスト通過」「安全になった」というAgentの文章ではなく、

- 実際のdiff
- CI
- scanner result
- candidate digest
- PR HEAD
- consumed approval token

をSource of Truthとして扱います。

---

## 9. 自分のリポジトリへ適用する場合

このCase Studyと同じ考え方を別リポジトリへ適用する場合、最初から複雑なMulti-Agent Orchestrationを作る必要はありません。

まずは次の順序で十分です。

1. TaskをMachine-readableにする。
2. allowed_paths / prohibited_paths を狭くする。
3. フェーズを跨ぐ作業には phase_contract を定義する。
4. BuilderとReviewerを分ける。
5. IndependentVerifierでAgent自己申告と独立したEvidenceを作る。
6. PR HEADにHuman Approvalをbindする。
7. mainをRulesetで保護する。
8. AIをPRで停止させ、人間が最終Mergeする。
9. 必要ならWorker/HumanのGitHub Credentialを分離する。

最初から「完全自律化」を目指すより、**どこでAIを止め、何を機械検証し、どこからHuman Authorityに切り替えるか**を明確にする方が重要です。

---

## 10. 関連リンク

- [AI Engineering Factory README](../../README.md)
- [Architecture Specification](../../ARCHITECTURE.md)
- [Security Policy & Guardrails](../../SECURITY.md)
- [Getting Started](../getting-started.md)
- [Factory PR #25: Phase Contract / Human Merge Boundary](https://github.com/moruku36/ai-engineering-factory/pull/25)
- [Web Security Control Lab](https://github.com/moruku36/web-security-control-lab)
- [Web Security Control Lab PR #1](https://github.com/moruku36/web-security-control-lab/pull/1)

---

## まとめ

この実験で最も重要だったのは、AI Agentの性能比較ではありません。

**Agentが賢くなるほど、Promptで役割を決めるだけでは足りず、役割・フェーズ・承認・Mergeの境界を機械的に表現する必要がある**、という点です。

Web Security Control Labで実際に境界違反を観測できたことで、AI Engineering Factoryの設計は「理論上のガードレール」から、実際の失敗を受けて強化された制御へ一段進みました。
