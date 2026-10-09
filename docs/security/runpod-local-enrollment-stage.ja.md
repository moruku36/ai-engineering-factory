# RunPod既存キーを一度登録する最小1段階（承認前・未実行）

## 最小の実段階

既存RunPod APIキー1個を本人がhidden入力 → Windows generic credentialへ保存 →
同じ許可コード内で読み込み、local readinessだけを返す。
operation IDは runpod.credential.local-use.once。
これはネットワークを使わず、キーが実RunPodアカウントで認証されるかは確認しない。
本体launcherの5role接続を待たず、Windows保存・再利用の基盤を先に導入できる。
秘密をモデルへ返すAPIは作らない。戻り値はstatusのみ。

新しい実接続候補:
orchestrator/runpod_local_credential.py
- run_owner_enrollment(scope, enabled=False): 既定無効の本人hidden UI → 保存 → local read接続。
- RunPodLocalCredentialFlow.enroll_owner / local_use_once / delete_owner: 同じ固定itemだけを扱う。
- current_windows_sid(): 実行中process tokenのSID照合候補。実行していない。
- source_pins(): 許可コード2ファイルとPython executableのSHA256を照合。
- module CLIはdisabled表示だけ。現段階でlive CLI/model toolへ登録していない。

LocalScopeはtrusted owner entryが具体的本人承認から供給する値。
confirmed=Trueは暗号学的な本人認証ではない。帰宅後の承認前にscopeを埋め、
信頼済みowner helperからrun_owner_enrollmentを呼ぶbootstrapが必要。
このbootstrapと既存本体launcherへのintegrationは**未実装**。
dummy storeでhidden UI→write→read→deleteのコード接続は検証する。
Win32 APIと実SID取得は未実行・未検証。無効経路ではDLLも資格情報も触らない。

## 一度の確認へ束ねる具体的scope一覧

| 項目 | 提案／確認する値 |
|---|---|
| 対象秘密 | 本人所有の既存RunPod management/provider APIキー1個のみ。新規キーを作らない。 |
| 登録UI | run_owner_enrollment。本人用対話terminalのgetpass、表示／echoなし。blank/Ctrl-C/EOFで取消。キーはchat・argv・env・ファイルに置かない。 |
| Windows保存item | AIEngineeringFactory/RunPod/provider/v1 （固定名）。このitemへのwriteは既存値があれば置換するため、そのscopeも本人確認に含める。 |
| 保存種別 | CRED_TYPE_GENERIC + CRED_PERSIST_LOCAL_MACHINE。同一ユーザー／同一PCのlogon間で保持。enterprise roamingは使わない。 |
| 本人SID | このthreadでは実値未採取。current_windows_sidまたは既存owner helperでローカル読取し、同じ実SIDをLocalScope.owner_sidへ設定・本人確認。公開repo/chatへ実SIDを載せない。 |
| 対象RunPodアカウント | このthreadでは実値未照合。既存owner helperの承認対象アカウントに合わせてprivate account_refを設定。local readiness成功はprovider account確認ではない。 |
| 許可launcher | RunPodLocalCredentialFlowのみ。既存Pod launcherはまだ許可対象へ追加しない。code pathsはこのmoduleとwindows_credential_store.py、owner側Python executable。 |
| hash | 上記code2ファイルのSHA256と本人端末のPython executable SHA256をsource_pinsで採取・照合し、本人確認表へ表示する。端末上のhashは未採取。変更すればscope再確認。 |
| 登録／確認の実行期限 | 提案: 本人確認から30分以内に登録と初回local read。具体的UTC期限をLocalScope.use_untilへ設定。延長は推定しない。 |
| 一回利用上限 | approvedな呼出し1回につきstore read1回、完了が10秒以上ならexpired。ネイティブ呼出しを強制中断するhard timeoutではない。自動retryなし。 |
| 保持 | キーは本人が削除／置換するまで保存。scope失効・process終了だけでは保存itemを消さない。利用承認期限と保存期限は別。 |
| 失効／削除 | scope期限後は利用不可。本人SID・hash一致時のdelete_ownerで固定itemを削除（期限後も削除可）。providerキーの失効は別の本人確認。 |
| 許可操作 | 保存、上記local read、本人登録解除だけ。RunPod account query／Pod作成・起動・削除／GPU／推論は追加しない。 |
| その他scope | Mattermost、5role追加登録、常駐、別account、ACL、network設定変更は対象外。 |

実SID・アカウント・端末上hash・UTC期限が未確定なので、現状の表を
「本人認証済み／保存可能」とは扱わない。それらをローカルで埋めた具体的表を
一度提示し、同じscope内の登録と初回readを一括承認してもらう。
既存RunPod単一試験の予算・期限は延長せず、今回のlocal stageで消費／開始しない。

## 本人への短い一括確認文（値を埋めてから提示）

> 表にある本人SIDとhashの許可コードに限り、既存RunPod APIキー1個を
> AIEngineeringFactory/RunPod/provider/v1へ一度保存（同item既存値があれば置換）し、
> 指定期限内にlocal readを一回確認してよいですか。キーは本人削除まで保持し、
> モデルへ値を返しません。Pod操作・課金・Mattermost・常駐・権限設定変更は含みません。
> 同一ユーザーの任意コード／管理者からの読取は防げない範囲を受け入れる確認です。

本人確認後のowner bootstrapはscopeをprivate runtime領域から供給し、statusだけ回収する。
キー入力自体は本人terminalだけで行い、AIがgetpassをtool経由で呼んで値を取得しない。
hidden inputのstrとPython内部copyの完全wipeは保証しない。mutable bufferはbest-effort消去。
登録後の日常local-useはUIを開かず、キー再入力・画面占有なし。
以後のライブlauncherには既存のbounded操作承認と別のintegrationレビューが必要。

## 次の接続と公式資料

RunPod実本体はmanagement/provider以外にもmodel/inference/control/journal signing key hex等の
roleを要求するため、今回の1キーだけで既存trialが動くとは主張しない。
既存fetch_account_idでの認証アカウント確認、provider_readerへの内部handoff、
typed str/hex変換、元のbudget/deadline/cleanupとの接続は後続。
secret-get APIやkey値をAIへ返す方法にはしない。

新しいネットワークqueryを勝手に実装しない。公式資料のGraphQLはdeprecatedで、
キーをURL queryへ付ける例があるため、新規用途で安易にコピーしない。
本段階はWindowsローカル利用だけとする。
[RunPod GraphQL現状](https://docs.runpod.io/sdks/graphql/configurations)、
[REST API v2](https://docs.runpod.io/api-reference-v2/overview)、
[キーの管理／失効](https://docs.runpod.io/get-started/credentials)。
Windows storeの保管／read／delete仕様は前の比較文書のMicrosoft公式参照に従う。

現在: 実秘密の登録・実CredWrite/Read/Delete・本人SID読取・権限設定変更なし。
追加ソフトとVault導入は不要。両PRはdraft、mergeしない。
