# Windows v2 providerを通常起動へ接続する

`orchestrator/runpod_startup_credential.py` は、Qwenの明示的な `start` / `serve`
から使う、既存provider資格の単回読出しを提供する。importだけではSID照会も
ストアアクセスも行わない。新規登録、削除、権限付与、自動入金は行わない。

アカウント確認用の承認は流用できない。別の `runpod.start.once` または
`runpod.serve.once` 承認が必要であり、コードの反映自体は実行許可にならない。
通常起動の料金・GPU・接続先・後処理の既存承認条件も維持される。

## 起動承認

`runpod-startup-v2-once-v1` の公開メタデータは、本人の端末内だけに置く。
このPRに承認済JSON、実SID、個人パス、account ID、鍵は含めない。

- `owner_approved`: 本人が別途承認した場合だけtrue。
- `approval_id`: 16〜64文字の新しいASCII識別子。失敗でも再利用不可。
- `owner_sid`: 本人WindowsプロセストークンのSID。
- `target`: 固定の `AIEngineeringFactory/RunPod/provider/v2`。
- `operation`: `runpod.start.once` / `runpod.serve.once` のいずれか。
- `issued_at` / `expires_at`: 有限UNIX秒。開始可能期間は最大300秒。
- `session_seconds`: 6000。起動受付の有効期間とは別の試験・後処理期限。
- `config_sha256`: 明示指定した非秘密operator設定のSHA256。
- `pins`: AI Governance Controlの関連4ファイル、Qwen起動3ファイル、明示指定operationsの
  `qmc_runpod` 全Pythonソース、実行PythonのSHA256。追加ファイルも照合対象。
- `factory_root`, `qwen_root`, `operations_root`, `python_exe`: 対象の絶対パス。
- `claims_dir`: AI Governance Control作業場所の親にある既存 `runpod-startup-claims` の絶対パス。

`public_pins(factory, qwen, operations)` は明示指定した公開ソースのみを読む。
承認を作る操作は提供しない。自動承認や他の資格情報候補への切替はない。

## 境界と時間

本人SID、全pin、設定digest、有効期間をclaim前・読出し前・読出し後・
試験開始直前に再確認する。claimは既存領域にO_EXCLで原子的に作る空ファイル。
同じapproval IDはプロセス再起動後も消費済み。失敗時の自動再試行はない。

公開ソースを先に捕捉・照合してから実行し、pycや別のambient packageを使わない。
ネイティブ読出しの受け入れ期限は10秒。親が読出し段階を27秒で監督し、
ハングした子を終了・回収する。起動待ちは最大300秒、試験全体は作業5400秒と
後処理600秒の既存計画に従い、親の監督期限6000秒、終了回収猶予3秒とする。

秘密値は子プロセス内のproviderへだけ渡す。親のIPC、argv、環境変数、ログ、
receiptには出さない。可変読出しbufferはfinallyで消去する。Pythonの不変文字列
コピーの完全消去は保証せず、子の終了で寿命を限定する。

Windows本人コンソールから他の既存資格を非表示入力する。接続先確認と個別の
削除承認も子のCONIN$/CONOUT$を使う。親には許可した状態語のみを返す。

OS停止・spawn/killの停止・スケジューラ停止・同一ユーザーによる任意コードや
管理者の改変・claim削除・子が作るSSH等の子孫プロセス終了は保証範囲外。
強制終了はPod停止・削除・課金停止の証拠にならない。試験開始後の期限超過や
終了未確認では `cleanup_required` を維持し、別途照合が必要な状態として返す。

## 検証範囲

テストは模擬SIDと模擬ストアだけを使う。実キー読出し、外部API、GPUは使わない。
単回claim、期限、SID/pin/設定変更、buffer消去、子の監督、実起動コードと
模擬providerの接続を検証する。Windowsの実コンソールおよび実v2キーを用いた
通常起動は未検証。過去の本人によるaccount確認成功と区別する。
