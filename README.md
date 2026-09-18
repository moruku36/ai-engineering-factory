# AI Engineering Factory

[![Security & Quality Gate CI](https://github.com/moruku36/ai-engineering-factory/actions/workflows/ci.yml/badge.svg)](https://github.com/moruku36/ai-engineering-factory/actions/workflows/ci.yml)

> **AIエージェントの実装を、隔離実行・検証証跡・人間承認付きPRに落とすためのガバナンス層です。新しいモデルでも巨大エージェント基盤でもありません。**

**現在のステータス: Experimental / MANUAL_ONLY (MIT License)**  
本番利用を前提とした完全自律開発プラットフォームではなく、AIエージェントを使ったソフトウェア開発を安全に工程化するための実験的な基盤です。現在の状態と制約は [PROJECT_STATE.md](PROJECT_STATE.md) を参照してください。

**⚡ 自分の環境で試す**: [15分クイックスタート (docs/getting-started.md)](docs/getting-started.md) — clone → `doctor` → `init` → サンプルタスク実行 → Evidence確認までの一本道シナリオです。

### 環境ごとにできること

| 環境 | CLI / 開発・テスト | Offline Container Isolation |
| :--- | :---: | :---: |
| Linux | ✅ CI Verified | ✅ CI Verified (Docker必須) |
| Windows | ✅ CI Verified | ❌ 未対応 (Linuxコンテナ前提) |
| macOS | ⚠️ Expected (未CI検証) | ❌ 未対応 |

「Docker Desktopが入っているから動くだろう」と思って`OfflineContainerRunner`をWindows/macOSで使おうとすると失敗します。隔離実行が必要な場合はLinux (またはWSL2、要検証) を使ってください。詳細は [Compatibility Matrix](docs/compatibility/matrix.md) を参照してください。

---

## 🎯 対象読者

| 向いている人 | 向いていない人 |
| :--- | :--- |
| • AIエージェントに自律実装させたいが、リポジトリ破壊や危険な操作を防ぎたい人 | • ワンクリックで何でもやってくれる完全自律ボットを探している人 |
| • エージェントの「Done」自己申告を信用せず、独立したテストと証跡で品質を担保したい人 | • 対話型チャットUIだけで完結させたい人 |
| • チームのPR・レビュー規約・承認フローをエージェントにも強制したい人 | • 実行環境のOS隔離やプロセスの後始末を気にしない人 |

---

## ⚖️ 現在できること / できないこと

エージェント基盤そのものを自作するのではなく、**外部エージェントを信用せずに安全に管理する**ことに特化しています。

| 今できること (Implemented & Verified) | 今できないこと (Out of Scope / Blocked) |
| :--- | :--- |
| **厳格なスキーマ & DAGスケジューリング**<br>JSON Schema (2020-12) に基づくタスク検証と依存関係の自動解決 | **Antigravityネイティブ実行 (BLOCKED)**<br>公式バッチCLI/コンテナSDKが未提供のため安全側に倒して拒否（架空接続は禁止） |
| **通信遮断型コンテナ隔離 & 成果物回収**<br>ネットワーク遮断Linuxコンテナでの実行と、パストラバーサルや保護パスを遮断した回収 | **完全自動マージ / 自動デプロイ**<br>すべてのマージや重要操作は人間の明示的レビュー・承認を必須とするガバナンス |
| **独立検証器 (Independent Verifier)**<br>エージェントの自己申告テストログを排除し、差分から実測 `candidate_digest` を照合 | **暗黙のフォールバック**<br>障害や非対応時に自動で安全基準の低い実行モードへすり替える動作は禁止 (Fail-Closed) |
| **本人認証付き承認 (Approval Token)**<br>HMAC-SHA256署名鍵とロール権限に基づく単回利用の暗号学的承認トークン管理 | **CLIによるワンライナー自律実行**<br>誤認防止のため単一の `run` / `ingest` CLIは提供せず、Python APIやテスト経由で制御 |
| **2相コミット操作ジャーナル**<br>SQLiteトランザクションによるGitHub操作の重複防止とクラッシュ復旧照合 | |
| **GitHub Ruleset ブランチ保護**<br>`main` ブランチへの直push / force push禁止、およびCI通過必須化の強制 | |
| **プロセスの安全停止**<br>タスクキャンセル時にアクティブなプロセスツリーを強制終了し、停止を確認してから状態遷移 | |

---

## 🚀 ライフサイクルの実像: 1つのタスクがPRになるまで

AI Engineering Factory では、エージェントによる独断実行を許さないため、**CLIの一発自動実行コマンド (`run` / `ingest`) は意図的に提供していません**。タスクの取込・隔離実行・証跡照合は CLI (`init` / `demo` / `doctor` / `approve`) と Python API (`ApprovedContainerLoop`, `OfflineContainerRunner`, `IndependentVerifier`) を組み合わせて段階的に制御します。

以下はフローの要約です。**自分のリポジトリで実際に手を動かして試す場合は、[15分クイックスタート](docs/getting-started.md) を参照してください**（`tasks/templates/basic-task.yaml` をテンプレートとして使い、`moruku36/ai-engineering-factory` のようなこのリポジトリ固有の値は自分の `owner/repo` に置き換えます）。

### 1. タスク仕様の定義
エージェントへの作業指示は、自然言語チャットではなく機械可読なタスク定義（YAML）として記述します（`schema_version`、`allowed_paths`、`validation`、`approval` などを持つスキーマ検証済みの構造体）。実例はこのリポジトリ自身を対象にした [`tasks/examples/sample-task.yaml`](tasks/examples/sample-task.yaml)、自分のリポジトリ向けのひな形は [`tasks/templates/basic-task.yaml`](tasks/templates/basic-task.yaml) を参照してください。

### 2. 環境診断・初期化・最小実行
```bash
pip install -e ".[dev]"

python -m orchestrator.cli doctor                              # 環境診断（Exit 2 = 正常 + MANUAL_ONLY）
python -m orchestrator.cli init --repository owner/repo        # 設定 + runtime-root を作成
python -m orchestrator.cli demo --task-file tasks/examples/sample-task.yaml --worktree .
python -m orchestrator.cli status                               # タスク状態台帳 (SQLite) の確認
```
`demo` は非隔離のローカル実行（`ManualAdapter`）でタスク→検証→Evidenceの流れを素早く確認するためのものです。信頼できないコードには使わないでください。

### 3. 隔離コンテナ実行と独立検証 (Python API)
未信頼な成果物に対しては、通信遮断コンテナ内でテストを実行し、自己申告ログを信用せずに実測 `candidate_digest`（64桁SHA-256）を独立検証します。`OfflineContainerRunner` はタグ付きイメージやフリーな `argv` を受け付けず、事前に登録された `sha256:` immutableイメージIDと `command_id` のみを実行し、Worktreeの読み取り専用スナップショットをマウントして `base_sha` との実差分を測定します。完全なコード例は [クイックスタート §7](docs/getting-started.md#7-the-real-isolation--verification-path) を参照してください。

### 4. マージ前の人手承認トークン発行 (CLI `approve`)
`approval.before_merge: true` のポリシーに基づき、人間オペレーターが署名鍵を用いて単回利用の承認トークンを発行します。
```bash
python -m orchestrator.cli approve \
  --action merge_pull_request --repository owner/repo --task-id TASK-001 \
  --head-sha <commit-sha> --target-ref refs/heads/main \
  --command "git merge task/task-001" \
  --policy-hash <sha256> --plan-hash <sha256> \
  --approved-by alice --key-file /path/to/operator.key
```
発行されたトークンは SQLite 状態台帳に記録され、GitHub 操作実行時に1度だけ消費（Consume）されます。PRのpush/作成自体はFactoryが自動で行うことはなく（`GitHubStatePublisher` の push/PR作成は未実装として明示的に例外を送出）、Evidence確認後に人間が `git push` / `gh pr create` します。

---

## 📚 用語集 (Glossary)

初めて本リポジトリを読むエンジニア向けの主要キーワードです。

| 用語 | 説明 |
| :--- | :--- |
| **SoT (Source of Truth)** | リポジトリのGitコミットおよびPR履歴。エージェントの一時記憶ではなく、リポジトリこそが真実の情報源です。 |
| **CAS (Compare-And-Swap)** | SQLite状態台帳の楽観的並行性制御。リビジョン番号を照合し、並列ワーカーによる競合や状態破壊を防ぎます。 |
| **runtime-root** | リポジトリ外に配置される使い捨て実行領域。生ログ、PID、一時DBをGit管理外へ完全隔離します。 |
| **Evidence Bundle** | テストログ、実行結果、成果物から計算された実測 `candidate_digest` を含む、改ざん不能な検証証跡。 |
| **Fail-Closed** | 異常、未認証、未検証項目に遭遇した際、例外をもみ消さずに「安全側に倒して即時拒絶（ブロック）」する設計思想。 |
| **Worktree** | Gitの複数ブランチを別ディレクトリに同時チェックアウトする機能。タスクごとのコード隔離に使用します。 |
| **Lease** | タスク実行権限の有効期限。タイムアウトやプロセス生存確認（PID監視）によりデッドロックを防止します。 |
| **Approval Token** | 人間オペレーターが署名鍵を用いて発行する、暗号学的に保護された単回消費型の承認証。 |
| **Adapter** | 外部のエージェントランタイム（Container, Manual, Antigravity等）と制御プレーンを繋ぐ抽象化層。 |
| **MANUAL_ONLY** | 現在の動作モード。完全自律ではなく、すべての重要操作に人間の介在を必須とする状態。 |

---

## 🏛️ システムアーキテクチャ概要

本システムは、AIエージェントに直接操作を許さず、**制御プレーン（Control Plane）** が単一の状態台帳（Single Writer + CAS）と厳格なスキーマによって全プロセスを統制します。

![AI Engineering Factory アーキテクチャ図（実装準拠版）](docs/architecture/images/architecture-diagram.png)

> 上図は現在リポジトリに実装されている範囲のみを描いています。Redis / S3 / Slack / Notion 連携やCI/CDでの自動デプロイなどは将来構想であり、現時点では実装されていません（詳細は [PROJECT_STATE.md](PROJECT_STATE.md) を参照）。

```text
要件定義 / 仕様策定 (JSON Schema)
        ↓
Machine-readableなTaskへ分割
        ↓
通信遮断コンテナ / Worktree で隔離実行
        ↓
独立検証器による証跡生成 (Evidence Bundle)
        ↓
品質ゲート検査 (Lint / Test / Secret Scan / Consistency)
        ↓
署名鍵による本人認証付き承認 (Human Approval)
        ↓
Pull Request 作成 → 人間による最終マージ
```

```mermaid
flowchart TD
    subgraph S1["① 入力・真実の情報源 (Source of Truth)"]
        Human["🧑‍💻 人間 / アーキテクト"]
        Spec["📋 要件・タスク定義 (JSON Schema)"]
        Repo[("📦 GitHub リポジトリ (SoT)\nmain (Ruleset Protected)")]
        Human --> Spec --> Repo
    end

    subgraph S2["② 制御プレーン (Control Plane)"]
        Ingest["タスク取込 / スキーマ検証"]
        Sched["依存関係スケジューラ / ポリシー"]
        StateLedger[("状態台帳 (SQLite + CAS)\n単一書き込み (Single Writer)")]
        CLI["運用 CLI (doctor / approve / cancel)"]
        Ingest --> Sched <--> StateLedger
        CLI -.-> Sched
    end

    subgraph S3["③ 実行・隔離境界 (runtime-root)"]
        Container["通信遮断型 Linux コンテナ / Worktree"]
        Collector["ArtifactCollector\n(パストラバーサル/保護パス遮断)"]
        Container --> Collector
    end

    subgraph S4["④ 検証 & ガバナンス"]
        Verifier["IndependentVerifier (実測 SHA 検証)"]
        Gate["品質ゲート (ruff / pytest / secret / pip)"]
        Approval{"🛡️ 本人認証付き承認\n(HMAC-SHA256 署名)"}
        PR["🚀 GitHub Pull Request"]
        Collector --> Verifier --> Gate --> Approval --> PR
    end

    Repo --> Ingest
    Sched ==> Container
    PR ==> Repo
```

> **詳細仕様**: 各コンポーネントの厳格な境界条件、状態遷移ライフサイクル、権限マトリクスは [ARCHITECTURE.md](ARCHITECTURE.md) を参照してください。


実際に利用する前に [PROJECT_STATE.md](PROJECT_STATE.md)、[OPERATIONS.md](OPERATIONS.md)、[Compatibility Matrix](docs/compatibility/matrix.md) を確認してください。

## 🛠️ 開発者・コントリビュータ向け検証 (Self-Test)

本基盤自体のコード修正やプルリクエスト作成時には、以下の自己検査を実行します。

```bash
# 静的解析 (Ruff)
ruff check orchestrator scripts tests

# 秘密情報漏洩スキャン (Fail-Closed)
python scripts/secret_scan.py

# 依存関係整合性確認 (pip check)
python scripts/audit_dependencies.py

# 回帰テストスイートの全実行 (193 tests)
pytest -v tests/
```

> **注意**: 本基盤の実行は現在「通信遮断型 Linux コンテナ (`OfflineContainerRunner`)」および「手動/モック (`ManualAdapter`)」が標準経路です。Google Antigravity Native Runtime は公式SDKが未整備なため現在 `BLOCKED` 判定としており、Antigravity の環境がなくても本基盤の全テスト・隔離実行機能は検証可能です。


## Repository構成

- `orchestrator/` — Control Plane、State、Policy、Scheduling、Execution Adapter、Publishing、CLI
- `schemas/` — Task、Plan、Result、State、ApprovalなどのMachine-readable Schema
- `tasks/` — Task Manifest、Plan、Active / Completed Example、Workflow Input（`tasks/templates/` に自分のリポジトリ向けひな形）
- `state/` — Version管理可能なState ProjectionやAudit Artifact。Transient Runtime StateはGit外に保存
- `.agents/` — Agent向けRepository-local Rule、Skill、Procedure
- `hooks/` — Lifecycle / Validation Hook
- `scripts/` — Security / Quality Validation Utility
- `docs/` — Architecture、ADR、Security、Operations、Compatibility、Design Rationale
- `.github/workflows/` — CIによるQuality / Security Gate

## Safety Model

Factoryは、Repository、Issue、Pull Request、Dependency、Prompt、Generated Commandなどをすべて潜在的にUntrusted Inputとして扱います。

Threat Modelには、以下を含みます。

- Prompt Injection
- Malicious Repository Content
- Malicious Issue / Pull Request
- Command / Shell Injection
- Path Traversal
- Secret Leakage
- Malicious Dependency
- Approval Bypass

Infrastructure Apply / Destroy、IAM / Credential変更、Public Exposure、Deployment / Release、Git History Rewrite、MergeなどのHigh-impact Operationは、Human Approvalを必要とします。

Automatic MergeやUnattended Production Deploymentは、このFactoryの目標ではありません。

詳細は [SECURITY.md](SECURITY.md) と [Threat Model](docs/security/threat-model.md) を参照してください。

## やらないこと

このプロジェクトでは、次のようなものを目標にしていません。

- Agent数を増やすこと自体を目的にした20〜50 Agent規模のSwarm
- 完全無人のSoftware Development
- ProductionへのAutomatic Deployment
- Automatic Merge Bot
- 特定モデルのPrivate Memoryへの全面依存
- Factoryを作るためだけの巨大なMicroservices / Agent Platform

まずSingle Agentでも確実に動作するWorkflowを作り、その後、本当に独立しているTaskだけMulti-Agent化し、安全性とEvidenceの境界が安定してからOrchestrationを自動化する、というIncremental Architectureを採用しています。

## 設計の参考にした資料

このFactoryの設計では、AnthropicやGoogleが公開している以下の考え方を参考にしています。

- Orchestrator–Worker Pattern
- Parallel Coding Agents
- Long-running Agent Harness
- Planner / Generator / Evaluator
- Structured Handoff
- Multi-Agent Critique / Verification Loop

特に、複数Agentを無制限に増やすのではなく、**依存関係を分析し、本当に独立したTaskだけを並列化する**という考え方を重視しています。

参考にした記事と、それぞれがFactoryのどの設計に反映されているかは、**[設計に影響した資料・参考文献](docs/architecture/design-influences.md)** に整理しています。

このプロジェクトは独立して開発しているものであり、Anthropic、Google、OpenAI、GitHubの公式プロジェクトではありません。

## Documentation

- [Getting Started (15分クイックスタート)](docs/getting-started.md)
- [Adapter Guide](docs/adapters/README.md) — Claude Code / Codex / 独自Adapterの繋ぎ方
- [Architecture](ARCHITECTURE.md)
- [Security Policy](SECURITY.md)
- [Operations Guide](OPERATIONS.md)
- [Contributing Guide](CONTRIBUTING.md)
- [Agent Specifications](AGENTS.md)
- [Project State](PROJECT_STATE.md)
- [Compatibility Matrix](docs/compatibility/matrix.md)
- [ADR](docs/adr/)
- [設計に影響した資料・参考文献](docs/architecture/design-influences.md)

## License

[MIT License](LICENSE) を採用しています。

