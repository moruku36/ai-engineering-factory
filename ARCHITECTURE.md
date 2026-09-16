# Architecture Specification (v1.0)

> **要件定義からプルリクエスト作成・人手承認までを安全にオーケストレーションするアーキテクチャ仕様書**

---

## 1. システムアーキテクチャ全体像

![AI Engineering Factory Architecture](docs/assets/architecture.jpg)

AI Engineering Factory は、自律型 AI エージェントのエンジニアリング作業を、決定論的かつ安全に管理するためのオーケストレーション基盤です。

### 全体データフロー & コンポーネント関連図

```mermaid
flowchart TB
    subgraph Layer1["① 入力・信頼できる情報源 (Source of Truth)"]
        Human["🧑‍💻 人間 / アーキテクト\n(PO, Engineers)"]
        Spec["📋 要件・設計・タスク計画\n(JSON Schema 2020-12 / Tasks)"]
        MainRepo[("📦 Git main ブランチ\n(検証済みコード・仕様 SoT)")]
        StateRepo[("📜 Git factory/state ブランチ\n(監査向け状態投影)")]
        Human --> Spec --> MainRepo
    end

    subgraph Layer2["② 制御プレーン (Control Plane: orchestrator/)"]
        direction TB
        Ingest["タスク取込 / 計画読込 / スキーマ検証"]
        Engine["ポリシーエンジン / 依存関係スケジューラ"]
        Lease["リース・並列実行管理 / 承認トークン管理"]
        Ledger[("状態台帳 (SQLite + CAS)\n単一書き込み (Single Writer)")]
        PRMgr["PR / 公開管理"]
        CLI["運用 CLI (doctor / status / approve / cancel)"]
        
        Ingest --> Engine <--> Ledger
        Engine <--> Lease
        Engine --> PRMgr
        CLI -.-> Engine
    end

    subgraph Layer4["④ 実行・隔離境界 (Execution Boundary: runtime-root)"]
        direction TB
        Worktree["タスク別 Branch / Worktree\n(一時的・使い捨て実行環境)"]
        Adapters["実行アダプタ\n(Antigravity / Manual / Subagent)"]
        Isolation["ランタイム隔離 / パス逸脱防止\nプロセス管理 / ポート隔離 / 生ログ・PID・一時DB"]
        Adapters --> Worktree <--> Isolation
    end

    subgraph Layer3["③ ワーカーレイヤー (Worker Layer: AI Agents)"]
        Builder["🔨 Builder\n実装・ビルド (allowed_paths)"]
        Tester["🧪 Tester / Validator\nテスト・検証・証跡生成"]
        Reviewer["🔍 Reviewer\nレビュー・合否判定 (ReadOnly)"]
    end

    subgraph Layer5["⑤ 品質・セキュリティゲート (Quality & Security Gate)"]
        direction TB
        Ruff["ruff check (Lint / Code Style)"]
        Pytest["pytest (Unit / Integration Tests)"]
        Sec["secret_scan.py & audit_dependencies.py"]
        CI["GitHub Actions CI (Linux / Windows)"]
        EvidenceGen["真正証跡集約 (Evidence Bundle / SHA-256)"]
        Ruff & Pytest & Sec & CI --> EvidenceGen
    end

    subgraph Layer6["⑥ 出力・人手承認 (Output & Human Gate)"]
        PR["🚀 GitHub Pull Request\n(候補変更 + 真正証跡)"]
        HumanGate{"🛡️ 人間によるレビュー / 承認\n(Human-in-the-Loop)"}
        MergedMain[("✅ main 反映\n(自動マージ・自動本番適用なし)")]
        PR --> HumanGate
        HumanGate -- "Approved" --> MergedMain
        HumanGate -- "Rejected" --> Ingest
    end

    MainRepo --> Ingest
    Engine ==> Adapters
    Worktree <--> Builder & Tester & Reviewer
    Builder & Tester & Reviewer ==> Layer5
    EvidenceGen ==> PR

    classDef sot fill:#e1f5fe,stroke:#0288d1,stroke-width:2px;
    classDef cp fill:#fff3e0,stroke:#f57c00,stroke-width:2px;
    classDef worker fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px;
    classDef boundary fill:#fbe9e7,stroke:#d84315,stroke-width:2px;
    classDef gate fill:#e8f5e9,stroke:#388e3c,stroke-width:2px;
    classDef human fill:#fffde7,stroke:#fbc02d,stroke-width:2px;

    class Layer1 sot;
    class Layer2 cp;
    class Layer3 worker;
    class Layer4 boundary;
    class Layer5 gate;
    class Layer6 human;
```

---

## 2. 設計の基本原則 (Core Principles)

| 原則 | 目的・動機 | 実装機構 |
| :--- | :--- | :--- |
| **単一の状態書き込み**<br>*(Single Writer)* | 複数エージェントや分散プロセスによる競合・デッドロック・状態不整合の完全排除。 | 状態遷移は `orchestrator.engine` 内の SQLite トランザクションと CAS (Compare-And-Swap) リビジョン番号で直列化。分散 Git ロックは禁止。 |
| **重要操作は承認必須**<br>*(Human-in-the-Loop)* | AI エージェントのハルシネーションや不正コードによる本番破壊・予期せぬ外部公開を防止。 | • `main` ブランチ直接 push 禁止（保護ルール必須）。<br>• 自動マージ・自動本番デプロイの全面禁止。<br>• 承認トークン（CLI: `orchestrator.cli approve`）と人間レビュー必須。 |
| **永続記憶はリポジトリ中心**<br>*(Git-backed SoT)* | すべての成果物・仕様・検証結果の再現性・監査性を長期的に担保。 | • `main` ブランチがコードおよび仕様（スキーマ・タスク定義）の真実の源泉 (SoT)。<br>• `factory/state` ブランチに監査用イベント履歴を投影。 |
| **SoT と使い捨てランタイムの完全分離**<br>*(Isolation Boundary)* | エージェントによるリポジトリ汚染、未管理ファイルの残留、シークレット漏洩の防止。 | 作業はすべて Git 外の `runtime-root` 配下の使い捨て Worktree で実行。生ログ、PID、一時DB、ソケットはリポジトリ外に閉じ込める。 |
| **安全側への倒しこみ**<br>*(Fail-Closed Validation)* | 境界外アクセスや未登録コマンド、未知スキーマのすり抜けを一切許容しない。 | 不明なスキーマフィールドの拒否、`shell=True` の排除、未定義コマンドの拒絶、CI 1項目失敗での即時停止。 |

---

## 3. 隔離境界: Git リポジトリ vs `runtime-root`

エージェントがアクセス可能な領域と、長期的な信頼境界は明確に物理分離されています。

| 領域 | 格納対象 | 保持期間 | アクセス権限 | 監査性 |
| :--- | :--- | :--- | :--- | :--- |
| **Git リポジトリ (SoT)**<br>`main` / `factory/state` | • 仕様・スキーマ (`schemas/`)<br>• 制御プレーン実装 (`orchestrator/`)<br>• タスク定義 (`tasks/`)<br>• 状態投影 (`state/`)<br>• ドキュメント (`docs/`) | 永続 (Git 履歴) | 制御プレーンのみコミット可能<br>エージェントは直接変更不可 | 高 (Git コミット履歴・署名) |
| **実行・隔離境界**<br>`runtime-root` (Git 外) | • タスク別 Worktree<br>• 一時ソケット・ポート<br>• プロセス PID ファイル<br>• 未加工の実行生ログ<br>• 一時 SQLite DB | 一時的 (タスク完了後に破棄) | Builder/Tester が隔離実行<br>`allowed_paths` スコープ内のみ | 中 (証跡バンドルに要約後、破棄) |

```mermaid
graph LR
    subgraph Repo["📦 Git リポジトリ (SoT / 永続境界)"]
        direction TB
        Code["ソースコード / orchestrator/"]
        Schemas["スキーマ定義 / schemas/"]
        TaskDefs["タスク仕様 / tasks/"]
        Audit["監査投影 / factory/state"]
    end

    subgraph Boundary["🛡️ 実行・隔離境界 (Isolation Boundary)"]
        direction TB
        WT["使い捨て Worktree (task-xxx)"]
        Logs["生ログ・PID・一時DB"]
        Sockets["一時ソケット・ポート"]
    end

    Repo == "1. タスクスナップショット展開" ==> Boundary
    Boundary == "2. 真正証跡 (Evidence) + PR 候補生成" ==> Repo

    style Repo fill:#e1f5fe,stroke:#0288d1,stroke-width:2px;
    style Boundary fill:#fbe9e7,stroke:#d84315,stroke-width:2px;
```

---

## 4. エンドツーエンド処理シーケンス

```mermaid
sequenceDiagram
    autonumber
    actor Human as 🧑‍💻 人間 / アーキテクト
    participant CP as ⚙️ 制御プレーン (orchestrator)
    participant Ledger as 📜 状態台帳 (SQLite + CAS)
    participant Runtime as 🛡️ 隔離境界 (runtime-root)
    participant Builder as 🔨 Builder Agent
    participant Tester as 🧪 Tester Agent
    participant Reviewer as 🔍 Reviewer Agent
    participant Gate as 🚦 品質ゲート (CI / Scripts)
    participant GitHub as 🐙 GitHub (PR / main)

    Human->>CP: タスク定義登録 (Task YAML)
    CP->>CP: スキーマ検証 & ポリシー検査
    CP->>Ledger: 状態更新: PROPOSED -> READY
    
    CP->>Runtime: 隔離 Worktree 作成 & リース獲得
    CP->>Ledger: 状態更新: READY -> RUNNING
    
    CP->>Builder: 実装ステップ指示 (allowed_paths 制約)
    Builder->>Runtime: コード変更適用
    
    CP->>Ledger: 状態更新: RUNNING -> VALIDATING
    CP->>Tester: テスト・検証指示 (独立セッション)
    Tester->>Runtime: pytest, Lint, ログ採取
    
    CP->>Gate: 静的解析 & セキュリティスキャン実行
    Gate-->>CP: 全ゲート合格 (Fail-Closed)
    
    CP->>Ledger: 状態更新: VALIDATING -> REVIEW
    CP->>Reviewer: 差分レビュー指示 (ReadOnly)
    Reviewer-->>CP: レビュー承認 & 真正証跡確定
    
    CP->>Ledger: 状態更新: REVIEW -> READY_FOR_MERGE
    CP->>GitHub: プルリクエスト作成 (候補変更 + 真正証跡)
    
    Human->>GitHub: コード & 証跡の確認
    Human->>CP: 承認トークン発行 (CLI: approve)
    Human->>GitHub: PR マージ (main ブランチ反映)
    
    CP->>Ledger: 状態更新: READY_FOR_MERGE -> DONE
    CP->>Runtime: Worktree & 一時リソース破棄
```

---

## 5. 品質・セキュリティゲート仕様

すべての変更は、以下のゲートをすべて **100% 合格 (Fail-Closed)** しなければ PR 作成およびマージに進むことはできません。

| ゲート種別 | 実行ツール / コマンド | 検証基準 (Pass Criteria) | 失敗時の振る舞い |
| :--- | :--- | :--- | :--- |
| **Lint / スタイル** | `ruff check .` | 警告・エラーが 0 件であること | 即時 FAILED 遷移 |
| **単体・結合テスト** | `pytest -q` | 全テストケースが PASS すること | 即時 FAILED 遷移 |
| **シークレット漏洩** | `python scripts/secret_scan.py` | API キー、トークン、秘密鍵の混入が 0 件 | 即時 FAILED 遷移・ログ秘匿 |
| **依存関係監査** | `python scripts/audit_dependencies.py` | 未承認パッケージ・既知の脆弱性・ライセンス違反なし | 即時 FAILED 遷移 |
| **CI パイプライン** | GitHub Actions (Linux & Windows) | マトリクス実行で全テストと解析が PASS | PR マージブロック |
| **証跡完全性** | Evidence Bundle Generator | SHA-256 ダイジェストとログ真正性が一致 | 承認トークン無効化 |

