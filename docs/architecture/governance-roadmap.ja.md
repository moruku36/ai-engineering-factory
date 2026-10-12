# ガバナンス・ロードマップ

*提案のみです。期限はなく、自動リリースもありません。G0（文書と表示名）は完了し、[PR #37](https://github.com/moruku36/ai-engineering-factory/pull/37) でマージ済みです。G1〜G5 は未実装です。今回の変更は計画の文書化のみで、以下のTDD追加は提案です。*

## 出典と位置づけ

着想は、Shun Kimura 氏の [AI Execution Accountability Framework — Discussion Draft](https://www.docswell.com/s/k1-c/Z9NDXY-2026-10-10-060401#p1)（表紙日付 2026-09-14、公開 2026-10-10）によります。これは議論用の資料であり、認証済み標準、規範的な製品仕様、法的判断、著者による推奨のいずれでもなく、当プロジェクトを認証するものでもありません。内容は当プロジェクトの言葉で要約しており、法令や外部資料に関する記述は未検証のため依拠しません。以下の段階は当プロジェクトによる翻案（Our adaptation）であり、草案の主張とは別のもので、著者が推奨するコードではありません。

参考にした考え方: 行為から出発し、リスク、必要な知識、責任者を結ぶ（[9-10頁](https://www.docswell.com/s/k1-c/Z9NDXY-2026-10-10-060401#p9)）。リスクに応じて実行者・確認者・責任者を分ける（[26-28頁](https://www.docswell.com/s/k1-c/Z9NDXY-2026-10-10-060401#p26)）。人間の役割（Actor/Reviewer/Owner）は [26-28頁](https://www.docswell.com/s/k1-c/Z9NDXY-2026-10-10-060401#p26) に記述されています。方針から資格、権限、証跡までをつなぐ（[31頁](https://www.docswell.com/s/k1-c/Z9NDXY-2026-10-10-060401#p31)）。

## 現状（main `8ef30734d041c7fa817c7dc5d4209fa2d31c8a8d`）

基準: main の完全なピン留めSHA [`8ef30734d041c7fa817c7dc5d4209fa2d31c8a8d`](https://github.com/moruku36/ai-engineering-factory/tree/8ef30734d041c7fa817c7dc5d4209fa2d31c8a8d)。以前の基準（`2525cbb`）からの変更はG0の表示と文書のみで、以下の実装に関する記述は再確認のうえ変更ありません。現在のプロジェクト状況は [PROJECT_STATE.md](../../PROJECT_STATE.md)、承認付きコンテナadapterとその制限は [APPROVED_CONTAINER_LOOP.md](../operations/APPROVED_CONTAINER_LOOP.md) を参照してください。

実装済み: タスクJSON Schema、DAG、単一のリスク列挙（`low/medium/high/critical`）、コマンド/パスポリシー、オフラインLinuxコンテナ、回収とIndependentVerifier（完全差分の制限は残る）、単回使用HMACトークンを扱うApprovalManager、ID/操作権限を扱うApproverRegistry、認証付きCLI approve（`cmd_approve`）、SQLite台帳/ジャーナル、GitHubチェック、COLLECTEDのみの受領、初期状態で無効なWindows/RunPodコード。HMACトークンの完全性・単回使用と、ApproverRegistryによるID・操作権限は別の仕組みです。実運用では保護されたレジストリと鍵の配備が引き続き必要です。状態は Experimental/MANUAL_ONLY で、根拠は模擬/CIであり、実キー、GPU、Windows Hello、Mattermostの証明ではありません。

AGENTSのAI Builder/Tester/Reviewerは工程上の役割で、草案の人間Actor/Reviewer/Ownerとは別です。既存の役割・鍵認証は、資格でも職務分離の自動保証でもありません。リスク理由・説明責任・資格を統合して受け入れ可否を判断する契約は存在しません。

## 段階（G0は完了、G1〜G5は提案）

**G0 — 名称と文書。** 表示名、ロードマップ、ADR、古い文書の訂正。受け入れでは、ソース内の表示文字列とテストの表示のみの更新は許容しますが、公開識別子とAPIの挙動は維持します。完了条件: 文書がマージされ、コード上の識別子やAPIの挙動が変わらないこと。PR #37 で完了済みです。

**G1 — 完全差分と評価。** 削除・モード・リネーム・不明なbaseの否定テストを含む完全差分契約。証明されるまで受領の拒否は維持します。タスク・候補・ポリシーに結び付く、別バージョンのガバナンス評価（行為、データ、外部影響、可逆性、理由、不明点、人間の評価者）を追加します。既存のリスク列挙は維持し、草案の「Moderate」は一括置換ではなく明示的な境界として `medium` に対応させます。`schema_version` の2020-12はJSON Schemaの版で、製品契約の版ではありません。完了条件: 各否定ケースがテストで拒否され、改ざんされた評価が拒否されること。

**G2 — 責任ある確認と承認。** 人間のActor/Reviewer/Ownerの役割と、リスクに応じた確認・分離。承認は評価、確認、候補、入力、コマンド、送信先、ポリシーのダイジェストに結び付け、使用前に期限と失効を再確認します。Python APIとCLIは共通のゲートを使い、ハード拒否は上書きできません。完了条件: 結合項目の変更や期限切れ・失効した承認者の利用が、両経路で阻止されること。

**G3 — 最小限の資格参照。** 発行者、方法、範囲、対象者、発行日時、期限/失効を記録します。LMSは作らず、研修やAIの自己申告を能力とは見なさず、資格が自動で認証情報を付与することもありません。不要な個人情報は公開しません。完了条件: 参照の欠落・期限切れ・範囲外が確認者の受け入れで拒否され、認証情報が変わらないこと。

**G4 — 説明可能なレポートと試行。** タスク、理由、確認、承認、実行、PRを結ぶJSONと人間向けレポート。不明点とCOLLECTED/verified/completedの区別を保ち、ハッシュだけでは真正性の証明になりません。確認時間、再試行、復元を測る小規模な試行を行います。完了条件: 試行1件をレポートだけで欠落なく再構成でき、測定値が記録されること。

**G5 — 実サービスadapterを1つ。** 前段のゲート通過後に、実際の公式機能に基づく範囲限定のadapterを一度に1つだけ扱います。範囲、予算、時間、停止、結果不明時の冪等な照合、外部の実クリーンアップを備えます。認証情報とRunPodは初期状態で無効のままです。モデルプロキシ、新UI、自動マージ、本番保証は含みません。完了条件: 実サービスでのリハーサルで、クリーンアップと照合が確認できること。

## 補足: TDD証拠の提案（未実装）

以下は、査読・採択が未確認のプレプリントをきっかけにした当プロジェクトの提案です。詳細は[研究サーベイ](../research/tdd-governance-2604.26615.ja.md)にまとめています。任意選択で期限はなく、上記の段階を置き換えず補足します。セキュリティ境界はすべて変更しません。G3は変更なしで、テストの質と人間の資格は別のものとして扱います。

- **G1:** タスクのphase/statusとは別に、版を持つTDDマイクロサイクルの証拠記録を設けます。差分処理を二重に作らず、完全差分契約の上に構築します。タスクと承認済み要件の版、base SHA、候補全体とスイートのダイジェスト、テストID、想定するREDの理由、runner/設定/依存関係の来歴、実測した実行結果、停止・例外の理由を結び付けます。同じ承認済み基準が、既知のbaseで失敗し、候補で成功することを求めます。この記録は任意選択です。文書のみの変更、挙動を保つリファクタ、既知のレガシー失敗については、適用、非適用、または宣言した例外を明示的に記録し、赤テストの捏造や自動免除はしません。文書変更のすべてにREDが必要というわけではありません。詳細は[サーベイ](../research/tdd-governance-2604.26615.ja.md)を参照してください。完了条件: RED欠落、別のbase、別のスイート、古い候補、未検出テスト、全スキップ、runner失敗の成功扱いが拒否され、削除・モード・リネーム・不明なbaseのケースも拒否されること。
- **G2:** GREEN/修復の間、実装担当は承認済みの基準を弱められず、承認済み受け入れスイートは読み取り専用です。変更には別の理由、確認、新しい版、再承認、再検証が必要です。フィクスチャ、スナップショット、期待値、skip/xfail、テスト検出、conftest、プラグイン、コマンド引数、依存関係、閾値、生成された評価データも追跡し、oracleの出所、実行者、承認者は別々に記録します。基準が変更された場合、影響を受けるRED/GREENの証拠、確認、承認は無効になります。完了条件: 基準の差し替え、削除、改名、選択範囲の縮小、全スキップ、古い証拠の再利用が拒否され、新たに承認された版だけが通ること。
- **G4:** 既存のワークフロー、TDDプロンプトのみ、エンジンの証拠契約のみ、両方、を同じセキュリティ境界で比べる試行です。共通の独立したoracleを使い、分母、失敗、コストを報告します。一部の条件しか実施できない場合、各要素の寄与は未検証です。生成スイートの合格率だけを主な成果にはしません。完了条件: 全試行が報告され、比較を再確認できること。
- **G5:** ゲート通過後に限り、既存の試行回数の範囲内で修復範囲を定めた範囲限定の公式adapterを扱います。失敗シグネチャ、パッチのダイジェスト、実効変更、累積の試行回数・時間・コストを、信頼できる永続的な台帳に残し、繰り返し失敗、変更なし、予算、範囲違反、不明の場合は停止します。再起動や新しいタスクの開始によって、予算や承認を暗黙にリセットすることはできず、結果不明の外部処理は再試行前に照合します。パッチの意味的同等性は、定義され検証されるまでは参考情報にとどまり、LLMによるハードゲートにはしません。N=3は推奨予算ではありません。完了条件: 停止と再起動の挙動が再現でき、結果不明時に二重実行が起きないこと。

## 補足: 権限・実行境界・認証情報の改修候補

**このプロジェクトに使えるか:** 使えます。範囲を限定して自律実行を任せるための設計資料として、まず G1 の評価と G2 の受入判断に三つの観点を追加し、G4 で検証してから G5 の操作代理 adapter を検討します。これは公開プロジェクトの改修提案であり、新規の会社案件、リリースの約束、実装済み統制ではありません。既存の説明責任と TDD の計画は維持し、G3 は変更しません。

### 出典と確認範囲

佐々木拓郎氏（NRIネットコム）、[生成AI時代の クレデンシャルとパーミッション設計](https://speakerdeck.com/nrinetcom/seisei-ai-jidai-no-to-pa-misshon-sekkei)。副題は「AIに権限と鍵を、どう渡し、あるいは渡さないのか」、Developers Summit 2026 KANSAI / A-6。表紙日付は **2026-08-21**、Speaker Deck 公開日は **2026-09-02**。末尾のロゴを含む全34スライドの本文と図を確認しました。以下は **ビューアのページ番号（1始まり）** で、フッターに印刷された番号があるページでは一つ小さくなります。例: ビューア25頁は印刷24頁です。末尾のロゴには印刷番号がありません。

資料は許可する操作、到達範囲、認証情報の渡し方を分けています（[4頁](https://speakerdeck.com/nrinetcom/seisei-ai-jidai-no-to-pa-misshon-sekkei?slide=4)）。文章の指示と設定・実行時 hooks（[12-13頁](https://speakerdeck.com/nrinetcom/seisei-ai-jidai-no-to-pa-misshon-sekkei?slide=12)）、許可リストと隔離を区別し、データ分類で配置を決める考え方を示しています（[15-17頁](https://speakerdeck.com/nrinetcom/seisei-ai-jidai-no-to-pa-misshon-sekkei?slide=15)）。秘密ストアの図では保管と取得権限を区別します（[20頁](https://speakerdeck.com/nrinetcom/seisei-ai-jidai-no-to-pa-misshon-sekkei?slide=20)）。ストアから注入した後は AI プロセスから値を参照できる（[24頁](https://speakerdeck.com/nrinetcom/seisei-ai-jidai-no-to-pa-misshon-sekkei?slide=24)）一方、操作代理では外部の実行主体が値を保持します（[25頁](https://speakerdeck.com/nrinetcom/seisei-ai-jidai-no-to-pa-misshon-sekkei?slide=25)）。鍵の寿命・外部での更新と人のログインは別に扱われています（[27-28頁](https://speakerdeck.com/nrinetcom/seisei-ai-jidai-no-to-pa-misshon-sekkei?slide=27)）。

これはカンファレンスの設計資料であり、安全性の認証、ベンチマーク、完全な認可プロトコルではありません。Claude Code の例を普遍的な構文や保証とは扱わず、設定をそのまま移植しません。コンテナにも mount、実行主体、通信、ホスト保護の検証が必要で、あらゆる脱出を防ぐ証明ではありません。鍵の四段階は露出の分析に使い、全環境で無条件に安全性を順位付けするものとは扱いません。短命鍵と更新の provider 対応は別途確認が必要です。以下の受入条件は **当プロジェクトによる翻案** であり、発表者の主張ではありません。

### 既存との重複と残る課題

main [`7bb92a1434dcdb067d0c1f919fa76b4ab518fe47`](https://github.com/moruku36/ai-engineering-factory/tree/7bb92a1434dcdb067d0c1f919fa76b4ab518fe47) と照合しました。AGENTS、CONTRIBUTING、`.agents/rules/RULE-001.yaml`、`RULE-002.yaml`、`.agents/skills/SKILL-001.yaml` を確認しました。役割・ルール・スキルの宣言だけでは実行時の強制を証明できません。

| 観点 | 既存との重複（実装の根拠） | 未実装・限界 |
|---|---|---|
| 権限と承認 | [PolicyEngine](../../orchestrator/core/policy.py) の hard deny・承認必須操作、[HookEngine](../../orchestrator/core/hooks.py) の trusted hooks。[ApprovalManager](../../orchestrator/core/approval.py) の実行文脈に結び付く単回 HMAC トークン、[ApproverRegistry](../../orchestrator/core/auth.py) の ID・操作権限確認。 | hooks があるだけでは全実行入口で必須ゲートを通る証明になりません。操作ラベルは同一ユーザーの任意コードに対する OS 制限ではありません。operator 鍵・registry の保護された配備、G2 の候補・評価との追加結合は未解決です。対話の確認はこのプロジェクトの暗号的承認とは別です。 |
| 実行境界 | [OfflineContainerRunner](../../orchestrator/core/container.py) は immutable Linux image、登録済み argv、通信遮断、非 root・読み取り専用実行、ホスト鍵の非 mount、trusted cleanup を実装。[ApprovedContainerAdapter](../../orchestrator/adapters/container.py) は登録 plan と入力 hash を結合。[運用上の限界](../operations/APPROVED_CONTAINER_LOOP.md)も参照。 | データ分類から runtime の受入可否を決める統一契約はなく、完全差分の限界も残ります。Linux CI は Windows 隔離や実モデル通信を証明しません。snapshot の無害化は trusted 前提で、任意の入力 bytes に秘密がないという保証ではありません。 |
| 鍵の取得と代理実行 | [既存 broker 提案](../security/local-credential-broker.md) に固定操作、別 ID、結果の秘匿、モデル所有プロセスの env/argv に渡さない設計があります。[LocalCredentialBroker](../../orchestrator/local_credential_broker.py) は合成値の同一プロセス grant、期限、再利用拒否、秘匿イベントを実装。Windows store と RunPod account adapter は休眠・既定 off。 | 既存提案を重複して作りません。`trusted_task` は harness が渡す文脈で認証 IPC ではなく、同一ユーザーコードは迂回できます。配備済み worker/broker 隔離の実証はありません。休眠 provider read は汎用の承認済み live adapter ではなく、今回実鍵は登録しません。 |
| 監査と寿命 | SQLite の承認・状態 journal、範囲限定 mock grant、cleanup 記録が基盤です。 | broker イベントは意図的に汎用 event/status のみです。境界判断を結合した報告や provider refresh の実証はありません。トークン・grant の期限と provider 鍵の寿命は別で、保存した静的鍵が短命になるわけではありません。 |

### 既存段階への改修候補（未実装）

- **G1 - 三つの観点を評価に追加。** 提案中の版付き評価に、許可 operation ID、データ分類（`public/internal/confidential/unknown`）、実行主体・profile、snapshot/mount と通信範囲、鍵の渡し方（`none/direct/injected/proxied`）と取得主体を追加します。値や capability handle を残さず、安全な参照で承認範囲と理由を記録します。公開データも無制限の実行を許可せず、不明な分類は評価されるまで提案する live 受入を止めます。出典: ビューア4、15-17、20-25頁。**受入条件:** 観点の欠落、未承認の runtime/mount/通信変更、別入力経路から秘密に到達できる場合は拒否します。合成値で env、子プロセス、store read API、file/mount、出力経路を検証します。G1 の完全差分基盤を再利用し、この追記で解決したとは扱いません。
- **G2 - 実行前の強制と承認範囲。** 上記評価を既存の承認 digest 提案と CLI/API 共通ゲートへ結合します。trusted な実行前チェックで実際の runtime 設定と操作範囲を検証し、指示文や worker が渡す `approved` を権限としません。hard deny、単回使用、人の承認を維持します。低影響操作のどれを登録済み限定 policy で任せられるか定義しますが、今回権限は広げません。出典: ビューア12-13、26、30頁。**受入条件:** 必須チェックの迂回・欠落・失敗、caller の偽装、操作・宛先・profile の変更、古い/失効した承認を両経路で拒否します。hooks は決定的なレビュー済み統制コードとし、LLM の安全判断を hard gate にしません。
- **G4 - 境界の証拠を試行。** 評価版、有効 policy/runtime digest、operation ID、許可/拒否の理由、承認参照、結果、cleanup 状態を安全に関連付けて報告します。合成 prompt injection 入力で範囲拡大や合成鍵マーカーの log・error・response 露出を検証し、拒否、確認時間、不明結果を測ります。COLLECTED/verified/completed の区別を維持します。出典: ビューア9、13、20、30-32頁。**受入条件:** 秘密・handle・私的 ID を出さずに試行1件を再構成でき、store read/外部送信の試みが拒否され、worker 出力に合成マーカーが現れないこと。限定シナリオの結果であり、一般的な prompt injection 耐性の保証ではありません。
- **G5 - 隔離された一操作の代理と寿命契約。** 前段ゲート通過後に既存 broker 提案を具体化します。固定一操作、保護された transport による caller 認証、別の保護された executor ID、許可リストの endpoint/method/型付き入出力、最小 provider 権限とし、汎用 secret-get/shell/URL tool を公開しません。worker が store、broker memory、継承された鍵の環境変数、保護設定を読めないことを求めます。出典: ビューア20、24-28頁。provider 鍵、操作 grant、人のログインは別の寿命です。更新は worker 外で provider 対応時のみ行い、task 承認・期限・予算を延長しません。ログイン喪失、失効、範囲変化、期限切れで新たな副作用を止め、不明結果は retry 前に照合します。**受入条件:** 実境界のリハーサルで store/process 直アクセス拒否、出力秘匿、失効 grant・ログイン喪失時の拒否、更新による範囲拡大や不明操作の無断再実行がないことを実証します。静的鍵のみの provider は限界を明記し、動的鍵を模擬して保証しません。登録・配備・provider 呼出は後続の具体計画と認可が必要で、Windows/RunPod は既定 off のままです。

この補足ではコード、本番設定、鍵、権限、公開識別子、互換 URL を変更しません。期限、自動マージ、本番保証、発表者の推奨という主張を追加しません。

## 前提条件

実サービスを扱う段階の前に、責任者、試行、データ、能力の発行者、最初のadapterを別途決定します。現時点で機能は追加しません。
