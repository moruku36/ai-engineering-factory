# Project State

## 現在のステータス: EXPERIMENTAL / MANUAL_ONLY

PR #7時点ではOS隔離や本人認証付き承認が未実装でした。その後のPR #12/#13（[通信遮断型Linuxコンテナ隔離](docs/operations/OFFLINE_CONTAINER_BOUNDARY.md)および[承認トークンとRun Loopの接続](docs/operations/APPROVED_CONTAINER_LOOP.md)）と5大コア領域改修によって、Linuxコンテナ隔離、本人認証付き承認、成果物検証、GitHub操作永続化、mainブランチ保護（Ruleset）が整いました。

しかし、Antigravity Native Runtime公式SDKが未提供（BLOCKED）であるため、現時点では**本番利用向けに認証・保証された完全自律開発プラットフォームではなく、MANUAL_ONLYです**。

このファイルは現在のHigh-level Statusをまとめたものです。過去の時点写しのReview / Handoff Documentは結論のみ本ファイルに残し、本文は削除済みです（詳細な議論の経緯はGitHubのPR履歴を参照してください）。

## 現在のCapability Milestone

5大コア領域の改修を実施：
- **本人認証付き承認発行と署名鍵管理**: 署名鍵とApproverRegistryによるHMAC-SHA256認証を実装。
- **成果物回収と独立検証**: パストラバーサル/symlink/保護パス遮断を伴うArtifactCollectorと、自己申告を排除したIndependentVerifierを実装。
- **Antigravity実接続評価**: 実機調査に基づきNative RuntimeステータスをBLOCKEDと確定、暗黙フォールバックを禁止。
- **GitHub操作の永続化と復旧**: 2相コミット型ジャーナルとクラッシュ照合、実測監視によるマージ検証を実装。
- **並列復旧・安全キャンセル・依存整合性検査**: プロセスツリー停止確認型キャンセルと依存関係整合性確認 (`pip check`) を実装。

全体の判定は、Antigravity Native Runtime公式SDK不在のため、依然として **MANUAL_ONLY** です。

- [x] **Execution Isolation & Boundaries**  
  Linuxの通信遮断型コンテナ実行と検証、保持型Port Reservation、安全な成果物回収（パストラバーサル/symlink/サイズ制限/保護パス遮断）および独立検証（candidate_digest実測・ログ自己申告排除）を実装。

- [x] **Approval, Trust & State Ledger**  
  単回承認トークンを隔離実行へ接続し、SQLiteへの結果保存・再起動時の照合を追加。鍵指紋導出・HMAC-SHA256本人認証付き承認発行（ApproverRegistryによる権限・失効検証）を実装。CLI承認発行を再有効化。

- [x] **Evidence & Quality Gates**  
  Secret Scan、依存関係整合性検査 (`pip check`)、実測candidate_digest照合、Lint / Test CIを実装。実行中ワーカーの安全なキャンセル（プロセスツリー停止確認）をCLIに実装。

- [ ] **Antigravity Integration (BLOCKED)**  
  Manual / Test Adapterは存在。実機調査により利用可能な公式バッチ実行/プロセス隔離SDKが不在であることを確認し、Native RuntimeをBLOCKEDと評価。暗黙のManual fallbackを厳格に遮断。

- [x] **GitHub Integration**  
  公開先・ブランチ・SHA・Open PRの照合、SQLiteによる2相コミット型ジャーナル永続化、障害復旧照合（reconcile_pending_operations）、実測監視によるHuman Merge検証、GitHub Rulesetによるmainブランチ保護を実装。

- [x] **Cross-platform CI**  
  GitHub ActionsでLinux / WindowsのValidationを構成。


## 現在のOperational Constraint

1. **`main`のServer-side ProtectionはGitHub Rulesetにより有効化されています。**  
   2026-09-17時点でGitHub Rulesetが適用され、Direct Push / Force Pushの禁止およびCI成功が必須化されています（`protected: true`）。オーケストレータ内部ポリシーと合わせた多層防御（Defense-in-depth）が成立しています。


2. **Projectは引き続きExperimentalです。**  
   Unit / Integration TestがPassしていても、すべてのOS、Antigravity Release、Agent Model、Repository Layout、Failure Modeを検証済みという意味ではありません。

3. **Antigravity ExecutionはHost Environmentに依存します。**  
   Native Sessionには互換性のあるLocal Runtime Componentと、利用者自身のAuthentication / Quotaが必要です。Factoryは存在しないSDK / CLI Capabilityを仮定・捏造してはいけません。

4. **High-impact OperationはHuman Approval対象です。**  
   Cloud Infrastructure Apply / Destroy、IAM / Credential変更、Public Exposure、Deployment、Release、Git History Rewrite、Mergeには明示的なHuman Approvalを必要とします。

5. **GitHubはDurable Engineering Source of Truthであり、Runtime Scratch Areaではありません。**  
   Active Database、Process Metadata、Lease、Raw Session Log、CredentialなどはRepository外のRuntime Boundaryへ保存します。

6. **Open Source Licenseは[MIT License](LICENSE)を採用しています。**  
   第三者によるReuse / Redistribution / Modificationは、MIT Licenseの条件下で許可されています。

## Documentationの優先順位

Status Document同士で内容が食い違う場合は、次の順序で判断します。

1. 現在の`main` ImplementationとCI Result
2. この`PROJECT_STATE.md`
3. `docs/operations/`配下に現存する運用ドキュメント（`APPROVED_CONTAINER_LOOP.md`、`OFFLINE_CONTAINER_BOUNDARY.md`、`runtime-isolation.md`）
4. それ以前のPhase / Review Recordは、結論のみここに残しHistorical Evidenceとして扱う（本文は削除済み。詳細はGitHubのPR履歴を参照）

過去に存在した `POST_PHASE4_REVIEW.md` は、Real Integration前の厳しいCheckpointを意図的に残したHistorical Reviewでした（結論は上の Capability Milestone に反映済み）。

過去に存在した `ISOLATION_APPROVAL_INTEGRATION_HANDOFF.md` の完了表記は最新レビューで撤回されています。モックによるテスト成功は実接続や隔離の証明ではありません。

## Public Repositoryとして今後やること

- [x] ~~第三者によるReuseを想定する場合はSoftware Licenseを選択・追加する~~（MIT Licenseを追加済み）
- [x] ~~Repository Settingsで可能になった段階で`main`のServer-side Protection / Required Checksを有効化する~~（GitHub Rulesetにより有効化完了）
- Compatibility Matrixを、実際に検証したVersionと常に対応させる
- 重要なRepositoryへ適用する前にDisposable RepositoryでReal Agent Runを検証する
- Multi-Agentによる生産性向上を主張する前に、Wall-clock Time、Retry Rate、CI Failure、Human Review Time、Cost per Merged Taskなどの実測値を蓄積する

