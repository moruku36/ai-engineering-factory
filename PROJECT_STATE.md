# Project State

## 現在のステータス: EXPERIMENTAL / MANUAL_ONLY

PR #7の再評価で、OSによる実行隔離、本人認証を伴う承認、Antigravityの実タスク起動が未実装と判明しました。最新の根拠と修正は [`POST_PR7_REVIEW.md`](docs/operations/POST_PR7_REVIEW.md) を参照してください。

継続的な技術検証を行える段階には到達していますが、現時点では**本番利用向けに認証・保証された完全自律開発プラットフォームではありません**。

このファイルは現在のHigh-level Statusをまとめたものです。`docs/operations/`配下のReview / Handoff Documentは、それぞれが確認したCommit時点の状態を記録しています。その後に統合された実装によって、古いReadiness判定が更新されている場合があります。

## 現在のCapability Milestone

追加改修: [通信遮断型Linuxコンテナ実行](docs/operations/OFFLINE_CONTAINER_BOUNDARY.md)を実装。
明示的な入力ファイルだけを渡すコマンド実行用の部品です。Native Adapter・承認・Run Loopとの接続は未完了で、全体の判定はMANUAL_ONLYのままです。

- [ ] **Execution Isolation & Boundaries**  
  Registered Command Execution、Path Containment、Process Tree Control、PID Reuse Protection、Task-scoped Runtime Resource、保持型Port Reservationは実装。OSによるファイル・ネットワーク隔離と実ワーカー検証は未完了。

- [ ] **Approval, Trust & State Ledger**  
  Cryptographically bound Approval Token、AtomicなSingle-use Consumption、Persistent SQLite State、CAS形式のState Transition、Retry Budget、Run Loopの一部を実装。セッション復旧、本人認証、ワーカーからの鍵・ストレージ隔離は未実装。CLI承認発行は停止。

- [ ] **Evidence & Quality Gates**  
  Secret Scan、依存関係整合性検査、Lint / Test CIを実装。CVE監査と独立した証跡検証は未実装。`doctor`はMANUAL_ONLYを返し、実行中ワーカーのCLIキャンセルは拒否。

- [ ] **Antigravity Integration**  
  Manual / Test Adapterは存在。Native Runtimeの検出だけでは起動証拠にならず、未実装のNative実行と暗黙のManual fallbackは拒否。

- [ ] **GitHub Integration**  
  公開先・ブランチ・SHA・Open PRの照合を実装。永続的な操作記録、障害後の照合、実接続の受入試験は未完了。

- [x] **Cross-platform CI**  
  GitHub ActionsでLinux / WindowsのValidationを構成。

## 現在のOperational Constraint

1. **`main`のServer-side Protectionは現在有効ではありません。**  
   2026-09-16時点でGitHub Branch APIは`protected: false`を返しています。Project PolicyとPublisher CodeではDirect Push to `main`およびForce PushをHard Denyしていますが、Repository Settings側のProtectionは別のDefense-in-depth Controlとして扱う必要があります。

2. **Projectは引き続きExperimentalです。**  
   Unit / Integration TestがPassしていても、すべてのOS、Antigravity Release、Agent Model、Repository Layout、Failure Modeを検証済みという意味ではありません。

3. **Antigravity ExecutionはHost Environmentに依存します。**  
   Native Sessionには互換性のあるLocal Runtime Componentと、利用者自身のAuthentication / Quotaが必要です。Factoryは存在しないSDK / CLI Capabilityを仮定・捏造してはいけません。

4. **High-impact OperationはHuman Approval対象です。**  
   Cloud Infrastructure Apply / Destroy、IAM / Credential変更、Public Exposure、Deployment、Release、Git History Rewrite、Mergeには明示的なHuman Approvalを必要とします。

5. **GitHubはDurable Engineering Source of Truthであり、Runtime Scratch Areaではありません。**  
   Active Database、Process Metadata、Lease、Raw Session Log、CredentialなどはRepository外のRuntime Boundaryへ保存します。

6. **明示的なOpen Source Licenseはまだ選択していません。**  
   RepositoryはPublicですが、第三者によるReuse / Redistributionを許可する場合は、Open Source Projectとして公開する前にLicenseを明確にする必要があります。

## Documentationの優先順位

Status Document同士で内容が食い違う場合は、次の順序で判断します。

1. 現在の`main` ImplementationとCI Result
2. この`PROJECT_STATE.md`
3. 対象Subsystemについて最も新しい日付のHandoff / Review Document
4. それ以前のPhase / Review RecordはHistorical Evidenceとして扱う

[`POST_PHASE4_REVIEW.md`](docs/operations/POST_PHASE4_REVIEW.md) は、Real Integration前の厳しいCheckpointを意図的に残したHistorical Reviewです。

[`ISOLATION_APPROVAL_INTEGRATION_HANDOFF.md`](docs/operations/ISOLATION_APPROVAL_INTEGRATION_HANDOFF.md) の完了表記は最新レビューで撤回しています。モックによるテスト成功は実接続や隔離の証明ではありません。

## Public Repositoryとして今後やること

- 第三者によるReuseを想定する場合はSoftware Licenseを選択・追加する
- Repository Settingsで可能になった段階で`main`のServer-side Protection / Required Checksを有効化する
- Compatibility Matrixを、実際に検証したVersionと常に対応させる
- 重要なRepositoryへ適用する前にDisposable RepositoryでReal Agent Runを検証する
- Multi-Agentによる生産性向上を主張する前に、Wall-clock Time、Retry Rate、CI Failure、Human Review Time、Cost per Merged Taskなどの実測値を蓄積する
