# Antigravity Runtime Integration & Network Boundary Evaluation

## 1. 調査概要
- **確認日**: 2026-09-16
- **担当**: Principal Software Architect / AI Engineering Architect
- **対象**: Google Antigravity (AGY) 公式SDK / CLI / ランタイムバイナリの実態調査
- **評価判定**: **BLOCKED**（公式Headlessバッチ実行APIおよびOS通信隔離が未充足）

---

## 2. 調査対象と確認結果

| 区分 | 調査対象 | 確認内容 / バージョン | 実機調査結果 | 判定 |
|---|---|---|---|---|
| **Python SDK** | `google-antigravity` (PyPI / GitHub `google-antigravity/antigravity-sdk-python`) | インストール有無・API仕様 | ローカル仮想環境に未インストール。ヘッドレス自動オーケストレーション用の権限・キーバインド未確立。 | **BLOCKED** |
| **公式CLI** | `agy` (Terminal TUI) | 実行ファイル有無 | ホスト環境に `agy` は不在 (`where.exe agy` -> NOT FOUND)。 | **UNAVAILABLE** |
| **内部CLI** | `agentapi.bat` (`C:\Users\kentaro\.gemini\antigravity\bin\agentapi.bat`) | サブコマンド確認 | 存在確認。サポートコマンドは `get-conversation-metadata`, `new-conversation`, `send-message` の3種のみ。 | **INSUFFICIENT** |
| **言語サーバー** | `language_server.exe` | バイナリの起動・インターフェース | 存在確認。対話的UI/エディタ統合用プロセスであり、外部オーケストレーター向けバッチ実行RPC仕様は非公開。 | **UNVERIFIED** |

---

## 3. 架空プロトコルの捏造禁止と安全境界要件

### A. バイナリ存在≠実接続可能
- `language_server.exe` や `agentapi.bat` のバイナリが存在しても、タスクの自律的開始 (`start_task`)、終了監視 (`poll`)、強制終了 (`cancel`)、成果物回収 (`collect`) を保証する公式仕様は存在しません。
- したがって、架空のJSON-RPCや未検証のサブプロセス呼び出しを捏造することは固く禁止します。

### B. 通信隔離（Network Boundary）と認証情報の保護
- モデルAPIへの接続が必要な場合、ホストの全ネットワーク（パブリックインターネット）を開放してはならず、必要なAPIエンドポイント（例: `generativelanguage.googleapis.com`）のみへの制限が必要です。
- ホストのユーザー認証情報（ブラウザクッキー、OAuthトークン）をワーカーに丸ごと渡すことは禁止され、タスク単位でスコープが限定されたエフェメラルトークンまたはプロキシ経由の通信が必須となります。

---

## 4. 結論と移行条件

- 現在の判定: **BLOCKED**
- 許可外通信の拒絶、架空プロトコル不採用、Native失敗時の暗黙のManual fallback禁止を強制します。
- 移行条件:
  1. `google-antigravity` SDKの正式導入と、コンテナ隔離環境下でのネットワーク宛先限定（Egress filtering）。
  2. タスク単位のエフェメラル認証トークンによるモデルAPI通信。
  3. 実セッションID・実測終了コードの追跡が可能な公式アダプターの実装。
