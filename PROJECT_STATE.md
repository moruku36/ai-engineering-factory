# Project State

## 現在のステータス: EXPERIMENTAL / INTEGRATION_VERIFIED

主要なExecution Isolation、Approval Integrity、Validation、Antigravity Adapter、GitHub Publisherの実装はPR #7までに`main`へ統合されています。

継続的な技術検証を行える段階には到達していますが、現時点では**本番利用向けに認証・保証された完全自律開発プラットフォームではありません**。

このファイルは現在のHigh-level Statusをまとめたものです。`docs/operations/`配下のReview / Handoff Documentは、それぞれが確認したCommit時点の状態を記録しています。その後に統合された実装によって、古いReadiness判定が更新されている場合があります。

## 現在のCapability Milestone

- [x] **Execution Isolation & Boundaries**  
  Registered Command Execution、Path Containment、Process Tree Control、PID Reuse Protection、Task-scoped Runtime Resource、Ephemeral Port Allocationを実装。

- [x] **Approval, Trust & State Ledger**  
  Cryptographically bound Approval Token、AtomicなSingle-use Consumption、Persistent SQLite State、CAS形式のState Transition、Retry Budget、Persistent Run Loop Controllerを実装。

- [x] **Evidence & Quality Gates**  
  Fail-closed Secret Scan、Dependency Audit、Lint / Test CI、実Git / Diff Evidence、Operator CLIの`doctor` / `status` / `approve` / `cancel`を実装。

- [x] **Antigravity Integration**  
  Native Runtime Probe / Adapterと、Manual / Test AdapterをExecution Abstractionの背後に実装。

- [x] **GitHub Integration**  
  Remote SHA VerificationとIdempotentなPR Query / Creationを含むPublisher Pathを実装。

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

その後の [`ISOLATION_APPROVAL_INTEGRATION_HANDOFF.md`](docs/operations/ISOLATION_APPROVAL_INTEGRATION_HANDOFF.md) では、Execution Boundary、Approval Integrity、Real Adapterなどの追加Hardeningを記録しており、その実装は後に`main`へMergeされています。

## Public Repositoryとして今後やること

- 第三者によるReuseを想定する場合はSoftware Licenseを選択・追加する
- Repository Settingsで可能になった段階で`main`のServer-side Protection / Required Checksを有効化する
- Compatibility Matrixを、実際に検証したVersionと常に対応させる
- 重要なRepositoryへ適用する前にDisposable RepositoryでReal Agent Runを検証する
- Multi-Agentによる生産性向上を主張する前に、Wall-clock Time、Retry Rate、CI Failure、Human Review Time、Cost per Merged Taskなどの実測値を蓄積する
