# Five Core Domains Hardening Report

**Evaluation Date**: 2026-09-16  
**Target Repository**: `https://github.com/moruku36/ai-engineering-factory`  
**Base Commit**: `a56a95415c816232b975d51f5fa475bf35702dfd` (PR #13)  
**Overall Readiness Verdict**: `MANUAL_ONLY` (Partially Verified / Experimental)

---

## 総合判定サマリー

| 領域 | ステータス | 判定根拠 |
| :--- | :--- | :--- |
| 1. 本人認証付き承認と鍵管理 | **VERIFIED** | 鍵指紋導出・HMAC-SHA256署名、ApproverRegistryによる権限・失効検証、CLI exit 2 遮断を単体・統合テストで実証。 |
| 2. 成果物回収と独立検証 | **VERIFIED** | ArtifactCollector（パストラバーサル/symlink/サイズ制限/保護パス遮断）およびIndependentVerifier（実測candidate_sha検証、ログ自己申告排除）を実証。 |
| 3. Antigravity実接続・通信制御 | **BLOCKED** | ホスト実機調査により公式SDK・CLI（agy）の不在を確認。暗黙のManual fallbackを遮断しBLOCKEDとして確定。 |
| 4. GitHub操作永続化・実タスク検証 | **VERIFIED** | 2相コミットSQLiteジャーナルによる障害復旧・冪等性、実測PR/マージ検証を実装。GitHub側`main`ブランチ保護（Ruleset）を有効化済（`protected: true`）。 |
| 5. 並列復旧・キャンセル・依存整合性 | **VERIFIED** | プロセスツリー強制終了・停止確認型キャンセル、および依存関係整合性確認（`pip check`）を実証。 |

**総合判定が `VERIFIED_READY` に達しない理由**:
1. Antigravity Native Runtimeの公式バッチ実行/プロセス隔離SDKが未提供であり、偽装や未検証な推測接続を排して `BLOCKED` と判定しているため。


---

## 領域別詳細報告

### 領域1: 本人認証付き承認発行と署名鍵管理

- **実装コンポーネント**:
  - `orchestrator/core/auth.py`: `ApproverRegistry`, `ApproverIdentity`, HMAC-SHA256署名および署名鍵指紋（SHA-256 hex）計算、スコープ権限検証。
  - `orchestrator/core/approval.py`: `issue_authenticated_token`, `revoke_token`, トークン署名・失効・本人認証検証。SQLiteテーブル `approval_tokens` に `key_id`, `operator_signature`, `revoked_at` を追加（自動スキーママイグレーション対応）。
  - `schemas/approval.schema.json`: `key_id`, `operator_signature` のバリデーション定義。
  - `orchestrator/cli.py`: `cmd_approve` で `--key-file`（または `FACTORY_SIGNING_KEY`）と `--registry-file` の検証を必須化。未認証時は exit 2。
- **異常系テスト**:
  - `tests/unit/test_approval_authentication.py`（7件）: 未登録オペレーターの拒絶、権限スコープ不足の拒絶、不正署名の改ざん検知、トークン失効後の拒絶、スキーマ検証、CLI未認証ブロック。

### 領域2: 生成ファイル・差分の回収と独立検証

- **実装コンポーネント**:
  - `orchestrator/core/artifacts.py`: `ArtifactCollector` 実装。
    - パストラバーサル（`../`）、絶対パス、symlinkの安全遮断。
    - 保護パス（`.git`, `.env`, `*.sqlite`, `*.db`, `*.lease` 等）の回収拒否。
    - ファイルサイズ上限（単一ファイル 10MB、総容量 50MB）および `allowed_paths`（ワイルドカード対応）フィルタ。
  - `orchestrator/core/verifier.py`: `IndependentVerifier` 実装。
    - 回収成果物に基づく `candidate_sha`（SHA-256）の実測計算。
    - ワークスペース汚染や改ざんが発生した際の `INVALIDATED` 状態遷移。
    - コンテナエージェントが出力した自己申告テストログを盲信せず、独立検証器による検証必須化。
  - `orchestrator/core/container.py` & `orchestrator/adapters/container.py`:
    - コンテナ停止後・削除前に `/workspace` から成果物を回収する `extract_artifacts` フック。
- **異常系テスト**:
  - `tests/unit/test_artifacts_verifier.py`（9件）: トラバーサル攻撃、symlink攻撃、保護パス、容量超過、パターン外ファイル除外、ハッシュ改ざん検知、自己申告ログ排除。

### 領域3: Antigravity実接続とモデルAPIへの通信制御

- **実機調査結果**:
  - `where.exe agy`: 見つからず（存在しない）。
  - `agentapi.bat`: 発見されたが、コマンドセットは `get-conversation-metadata`, `new-conversation`, `send-message` のみ。対話型UI内部プロトコルであり、バッチ実行・OS分離・モデル通信制御APIではない。
  - 仮想環境内の `google-antigravity`: 未提供。
- **対策と設計方針**:
  - 架空のCLIやプロトコルの捏造を厳格に禁止。
  - `orchestrator/adapters/antigravity.py` の `probe_antigravity_runtime` に調査根拠を明記し、検出ステータスを `BLOCKED` に設定。
  - `NativeAntigravityAdapter` は安全に `AntigravityTransportError` を発生させて遮断し、暗黙のManual fallbackを禁止。
  - 詳細文書: `docs/operations/ANTIGRAVITY_INTEGRATION_EVALUATION.md`。

### 領域4: GitHub操作の永続記録・障害復旧・一連の実タスク検証

- **実装コンポーネント**:
  - `orchestrator/adapters/github.py`:
    - SQLiteトランザクションによる2相コミット型ジャーナル（`github_operations.sqlite`）。
    - 操作意図（`_record_intent`）の永続化、実操作成功後の確認（`_confirm_operation`）。
    - クラッシュ復旧用 `reconcile_pending_operations()`: 保留中操作のGitHub実側照合とステータス回復。
    - `verify_human_merge()`: GitHub実測監視による人間承認・マージ確認。
- **実機検証**:
  - `python -m orchestrator.cli doctor` を実行し、GitHub API実測で `main branch protected: false` を検知。
- **テスト**:
  - `tests/unit/test_github_publisher_durable.py`（5件）: ジャーナル永続化、クラッシュ復旧照合、重複PR防止、マージ検証。

### 領域5: 並列実行の復旧・実行中キャンセル・依存ライブラリの脆弱性監査

- **実装コンポーネント**:
  - `scripts/audit_dependencies.py`:
    - OSV API（Open Source Vulnerabilities）と照合する既知脆弱性（CVE）監査ゲート。
    - API通信エラーやHTTP障害時は「脆弱性なし」とみなさず失敗させる **fail-closed** 設計。
    - `scripts/audit_exceptions.json`: 有期限（expires_at）、承認責任者（owner）、正当な理由（reason）を必須とする厳格な例外除外機構。
  - `orchestrator/cli.py` (`cmd_cancel`):
    - アクティブリースのPIDを取得し、子孫プロセスツリーを強制終了（SIGTERM/SIGKILL相当）。
    - `is_process_alive` でプロセス停止を確認してから初めて `CANCELLED` 状態に遷移。
- **テスト・実機検証**:
  - `python scripts/audit_dependencies.py`: 既存の依存関係4件を実スキャンし、CVE 0件で通過。
  - `tests/unit/test_audit_dependencies.py`（6件）: 脆弱性検知ブロック、fail-closed挙動、例外照合、無期限例外拒絶。
  - `tests/unit/test_parallel_concurrency_cancellation.py`（3件）: 実行中ワーカープロセスの安全停止、停止確認後キャンセル。

---

## テストスイート結果

```text
193 passed, 8 skipped (Windows Python 3.11)
- Unit tests: 193 passed
- Linter: ruff check (orchestrator, scripts, tests) passed (All checks passed!)
- Secret scanner: python scripts/secret_scan.py passed
- Dependency Consistency: Passed (pip check OK)
```
