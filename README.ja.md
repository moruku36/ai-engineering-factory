# AI Governance Control

[English](README.md) | [日本語](README.ja.md)

**Experimental / MANUAL_ONLY** ・ Python 3.11 以上

## 1. 何をするものか

人間または外部エージェントによる編集を扱う、タスク・検証・承認の基盤です。コードを自律的に書くことはしません。流れは タスク/編集 -> チェック -> PR -> 人間の承認 です。自動マージ・自動デプロイはありません。

表示名を変更しました（旧称 AI Engineering Factory）。リポジトリ名、パッケージ、CLI は変更ありません。

## 2. 構造

- `orchestrator/`: 状態、ポリシー、実行、承認、GitHub確認
- `schemas/`, `tasks/`, `config/`, `tests/`, `scripts/`, `.github/`: 契約、テンプレート、CI
- `docs/`: 詳細。DB・ログ・認証情報はリポジトリの外に置きます。

## 3. 実装済み・未実装・未検証

**実装済み:** タスクスキーマとスケジューリング、通信を遮断したLinuxコンテナ実行・回収・独立検証器、単回使用の署名付き人間承認とジャーナル、ブランチ公開とPR API。受領が記録するのは `COLLECTED` のみで、`VERIFIED` や `COMPLETE` ではありません。Windows資格情報とRunPod起動のコードは初期状態で無効で、使うには別途、人間の承認が必要です。

**未提供:** 自動マージ・自動デプロイ、Claude Code/Codex のネイティブadapter。現在の本製品ではAntigravityはブロックされています。

**制限・未検証:** 完全差分の扱いには制限があり、引き渡しではそのタスクを拒否します。隔離はLinuxのみです。CIは通常のUbuntuとWindowsが対象で、macOSとWSL2は未検証です。模擬テストは、実キー、GPU、Windows Hello、Mattermostの証明ではありません。プロセス停止だけでは、Pod削除や課金停止を確認できません。

### Safety model

影響の大きい変更には人間の承認が必要です。Fail-Closed で動作し、必要な検査や制御が使えない場合は停止します。黙って弱い方式に切り替えることはありません。秘密情報はチャットやログに出しません。

## 4. 最短の開始手順

Python 3.11 以上の仮想環境を用意し、クイックスタートに従って有効化してください。

```bash
git clone https://github.com/moruku36/ai-engineering-factory.git
cd ai-engineering-factory
pip install -e ".[dev]"
python -m orchestrator.cli doctor
python -m orchestrator.cli demo --task-file tasks/templates/basic-task.yaml --worktree .
```

検査が通れば、doctorの終了コード2は想定どおりです（MANUAL_ONLY）。demoは信頼できる既存の編集を確認するだけで、AI起動、隔離、パス制限の強制、独立した証拠はありません。

## 5. ドキュメント

[プロジェクト状態](PROJECT_STATE.md) ・ [アーキテクチャ](ARCHITECTURE.md) ・ [運用](OPERATIONS.md) ・ [セキュリティ](SECURITY.md) ・ [クイックスタート](docs/getting-started.md) ・ [Adapter](docs/adapters/README.md) ・ [互換性](docs/compatibility/matrix.md) ・ [引き渡し](docs/operations/HANDOFF_V01.ja.md) ・ [起動時の認証情報](docs/security/runpod-startup-credential.ja.md)

今後の計画（未実装）: [ガバナンス・ロードマップ](docs/architecture/governance-roadmap.ja.md)

[MIT License](LICENSE)
