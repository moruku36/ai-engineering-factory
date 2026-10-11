# 本人確認用：ローカル資格情報利用（mock完成、実導入は未実施）

現在はdraft PR #31。merge・実キー登録・Win32 API実行・常駐設定はしていません。
通常broker経路はキーをモデルへ返さず、固定状態値だけを返します。
同じWindowsユーザーの任意コードや管理者からの読取には隔離不十分です。
この脅威範囲を理解して便利さを選ぶ判断は可能で、絶対隔離を導入条件に追加しません。

## 帰宅後の短い確認案（今は確認を取らず、実行もしない）

> 既存RunPodキーを専用の非表示入力へ一度登録し、このPCの資格情報領域に
> 本人削除・更新まで保持する案です。AIへは短期限・単回の参照だけ渡します。
> 対象は既存の承認済みRunPod単一試験とMattermost最大5分監視に限定し、
> 元の予算・対象・終了期限を維持します。期限不明なら実行しません。
> Mattermost tunnel keyは引き続きprocess-onlyとし、永続登録は別確認です。
> 通常の戻り値・ログにキーを出さない一方、同一ユーザー／管理者からの隔離は
> 保証しません。追加課金サービス・別アカウント・ACL変更・常駐・ネットワーク
> 設定変更を含めず、この範囲で導入準備を進めてよいですか。

実登録前には、対象launcherの実ファイル・関数・版と具体的既存承認の
予算／期限を担当threadが照合し、この確認の対象へ束ねて提示してください。
現在その実ファイル名や承認数値はこのthreadに渡されていません。
値・端末識別子・private destinationをpublic repoへ書かないでください。

## 登録UIの成果物

orchestrator/credential_enrollment_mock.py:
- run_mock_enrollment(read_hidden, write_safe, store)：本人非表示入力、取消、
  synthetic値限定登録。Windows storeと他の入力は拒否。
- main()：手動のmockデモ。非対話入力ならpromptせず終了。終了時にmock削除。
- 入力は公開dummyのsynthetic-fixtureだけ。実キーを入力しない。
- 自動実行時に画面を開くコードはない。本人入力は一度だけの対話として設計。
  現時点はmockデモのため終了すると再入力が必要。実永続版は未接続。

承認後の実登録UIは固定serviceとtrusted storeを結び、同じ非表示入力・取消・
固定状態表示を使う予定。mockのsynthetic限定チェックを勝手に解除しない。
Win32 storeのenabled=Trueも本人登録の具体的承認まで有効化しない。

## adapter引継ぎの対象ファイル・関数

| AI Governance Control内の実在ファイル／関数 | 引継ぎ役割 |
|---|---|
| orchestrator/windows_credential_store.py / WindowsCredentialStore.write, read, delete | 承認後だけ使用する保存候補。実API未検証。 |
| orchestrator/local_credential_broker.py / LocalCredentialBroker.enroll_trusted, execute, revoke_trusted, delete_trusted | 登録・固定操作・参照失効・削除・監査秘匿の基本候補。 |
| orchestrator/credential_enrollment_mock.py / run_mock_enrollment, main | 本人登録のmock UI。実登録へは未接続。 |
| orchestrator/bounded_credential_mock.py / TrialApproval, AdapterContext, BoundedMockBroker | 元の試験承認、対象、予算、期限を保持する契約。mock identityのみ。 |
| orchestrator/bounded_credential_mock.py / fixed_mock_adapter(value, context) | 既存launcher側のadapterが実装すべき関数契約。現在は固定mock。 |
| tests/unit/test_bounded_credential_mock.py | UI、画面非使用、予算・期限保持、取消・失効・削除を再現するsyntheticテスト。 |

RunPod本体の接続先：既存の単一trial実行／予算確認／終了・cleanup関数。
Mattermost本体の接続先：既存の最大5分monitor実行／cancel／終了cleanup関数。
**実パス・関数名は未提示のため未照合**。本体ファイルは変更していません。
担当threadがactual functionをこのadapter契約へ対応付け、固定target・operationを
設定する必要があります。任意exe/argv/URLをworker入力から受け付けません。

## bounded契約と保持・失効・削除

- 固定operation ID：runpod.trial.once、mattermost.monitor.once。
- 元承認をtrusted TrialApprovalに保持し、target_ref、budget_cap、deadline、
  plan_digestをimmutableに渡す。workerに予算・期限・対象上書き欄を出さない。
- 承認1件につきhandle発行は一度。単一試験を新しいhandleで反復しない。
  参照開始期限は最大60秒、監視本体は元期限以下かつ最大5分。
- キャンセル・登録解除はpendingを失効し、実行中へcancel eventを送る。
  stubでは終了時に状態値だけ返し、入力／adapter bufferをbest-effort消去。
- 実adapterはcancel event／deadline／予算を副作用前と監視中に確認し、
  既存cleanup・remote reconcileへ接続する。stub成功は実Pod停止やtunnel失効の
  証拠ではなく、予算をprovider側へ強制する機能もまだない。
- 実保存するRunPodキーは本人削除・更新まで保持する提案。参照期限とは別。
  ローカル削除とprovider key失効は別操作。登録解除後はキーを再発行しない。
- tunnel keyはprocess-only。監視終了でbufferを破棄し、既存remote session終了を
  確認する。ここでは実tunnel・port・network設定を変更しない。

## 残る導入判断

mock UI・契約・テストはreview可能です。実導入前に既存launcherの対応先確認、
実専用UIへの接続とWindows native動作確認が必要です。
本人確認は上の対象を具体化して一回にまとめます。課金上限や期間の延長は
この登録確認から推定しません。Vault等の追加ソフト導入は今は不要です。
