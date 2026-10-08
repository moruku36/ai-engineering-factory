# ランチャー ↔ ブローカー対応付けドラフト(モックのみ・未接続)

状態: **提案ドラフト。本日は何も接続しない。** 公開ドラフト PR として提出、マージなし。

- ブランチ: `proposal/launcher-mock-bridge-20261008`
- ベース: PR31 head `357ebec63d12e4c72e90ced3327f13528064afa5`(`.git` の ref ファイルで一致を確認)
- 初期追加ファイルはこの文書と `docs/examples/local-credential-broker/launcher-bridge-mock.py` /
  `launcher-bridge-mock.test.py` の 3 点のみ。初期実装ではPR31の既存ファイルとworkflowは未変更。今回レビューで既存CIのstacked PR対象とsynthetic bridgeテストstepを追加しました。

## 1. 今回の成果物が示すこと/示さないこと

`BoundedMockBroker.execute` は `fixed_mock_adapter` を直接呼び、**実アダプタの登録フックを
持たない**。したがって今回の合成ハーネスはランチャーをブローカーに接続していないし、
接続できるとも主張しない(monkeypatch・サブクラス上書き・private 参照はしていない)。

ハーネス `TrustedLauncherBridgeMock` が行うのは次の合成(composition)だけ。

1. 既定 `enabled=False`。無効時は登録・grant の前に `disabled` を返し、プロンプトも出さない。
2. 有効時、既存 `run_mock_enrollment` を 1 回だけ実行(hidden コールバック呼び出しは最大 1 回、
   入力は `synthetic-fixture` 完全一致のみ)。メモリ上の `MockCredentialStore` 1 個に入る。
3. その 1 個のストアを 2 つの固定 operation(`runpod.trial.once` /
   `mattermost.monitor.once`)で再利用。実行ごとに別の一回限り `TrialApproval` が必要。
4. `broker.execute` が既存の固定スタブを呼び、`ok` を返した**後に限り**、資格情報を一切
   持たない fake ランチャーのライフサイクル形状を実行する。
5. `close()`(`with` の `finally` 相当)でブローカー経由の削除とストア削除を必ず行う。

検証できるのは**オーケストレーションの順序とクリーンアップ契約**であり、
**実際の秘密の受け渡しは検証していない**。fake は登録済みストアの値を受け取らず、
固定プレースホルダだけを読む。そのプレースホルダは `bytearray` の抽象であり、実 provider の
`str` + 署名鍵 hex デコードとは型が違うため、**fake は実ランチャーの drop-in ではない**(§2)。fake のクリーンアップフラグは合成の帳簿であり、
実 Pod 削除や実課金停止の保証ではない。

公開結果は `{"status": ...}` のみ(`disabled / ok / denied / failed / cancelled / expired /
cleanup_incomplete`)。ハンドル、ID、資格情報値、プロバイダ応答、例外文字列は返さない。
監査は許可リストの `event` / `status` のみ。無効・期限切れ・タスク違い・再利用の拒否は
既存ブローカーの判定に依拠し、fail closed。ハーネス側は追加で `target_ref` /
`plan_digest` の合成定数一致と `budget_cap == 0` を要求する。

### 限界(必読)

- このモデル API は**同一プロセス内の敵対的コードに対して身元を強制できない**。
  `trusted_task` は信頼済みハーネスが渡す値で、認証されたものではない。
- **強制キャンセルはできない**。キャンセルと期限は協調的で、`stopped()` を見ない処理は
  止まらない。
- ワイプは `bytearray` のコピーに対してのみ有効。hidden コールバックが返す `str` や
  Python 内部のコピーは消せない。完全な文字列ワイプは主張しない。
- ブローカーの `AdapterContext`(cancel / deadline)はハーネスから取得できない。fake 側は
  別の協調コンテキストを使っており、ブローカーの期限と同一物ではない。
- 合成で live コールバックはテストできない。**アダプタ束縛(adapter binding)が欠けて
  おり**、実ランチャー側の変更は別途の承認とレビューが必要。
- 共有ストアなので、どちらか一方の operation の `delete_trusted` で両方が使えなくなる。
  実運用で役割別ストアが必要かは未決(§4)。

## 2. RunPod 対応付け(現状の記述と将来の境界)

> **確認者の区別**: 以下の実ランチャーの記述は、Codex が既存の不変ソース
> (`runpod-owner-helper` と、`runpod_provider.py` / `runpod_trial.py`)を独立に読んで
> 照合したもの。role 名と型の
> 対応は Codex により正しいと確認済み。**この文書とモックの作成者(Claude)は実ランチャーの
> ソースを読んでいない**。実 ID・実パスなどの非公開値はここに記載しない。

現行経路:

- `runpod-owner-helper` の `protected_injection(path, sid, protector / provider_module /
  provider_reader / account_reader)`。provider プロンプトの**前に**検証されるのは
  **Windows owner、config、pinned sources の 3 つだけ**。
- **DPAPI による auth の復号はプロンプトの前ではない**。公式アカウント確認の**後**に行われる。
- `provider_reader` が扱うのは management key のみ。
- `runpod_provider.open_injection(config, owui=False, secret_reader=...)` の `secret_reader`
  は次の role 名で呼ばれる: `provider` / `model` / `inference` / `control` /
  `journal signing key hex`(最後は `journal` ではなく、この文字列と完全一致)。
- 型: 実 provider は各 role の値を **`str`** で受け取り、署名鍵は **hex デコード**する。
- 型付き `Injection` → `runpod_trial.run_injected(..., owner_start=True)`。
- 実 ID は `fetch_account_id` の `consumerUserId` で確認。
- 上限: 作業 90 分 + cleanup 10 分 = 100 分で失効、合計 10 USD(うち cleanup 1 USD)。
  **プロバイダ側のハードキャップは保証されていない**。retained Pod は対象外。

モックとの対応:

| 実経路 | モック | 差分 |
|---|---|---|
| プロンプト前の owner / config / pins 検証 | なし | モックはいずれも検証しない |
| 公式アカウント確認 → DPAPI auth 復号 | なし | モックは順序も復号も再現しない |
| `open_injection(config, owui=False, secret_reader=)` | `_FakeRunPodLauncher.open_injection` | role 名は実物と同じ 5 個。値は固定プレースホルダで、ストア値は渡らない |
| role 値の型(`str`、署名鍵は hex デコード) | `bytearray` プレースホルダ | **型が違う。fake は drop-in ではなく、実際の型付き受け渡しが欠けている** |
| `run_injected(inputs, owner_start=True)` | `_FakeRunPodLauncher.run_injected` | Pod 作成は bool フラグ。ネットワークなし |
| journal close | `journal_closed` | 合成フラグ |
| Pod 削除と不在確認 | `pod_absent`(journal とは別) | 合成フラグ。実不在の証拠ではない |
| 90 / 10 / 100 分、10 / 1 USD | 未モデル化 | モックは `budget_cap == 0` と承認期限のみ |

実アダプタ境界で必要なこと(未実装):

- `TrialApproval` の `deadline` / `budget_cap` / `target_ref` / `plan_digest` を、ブローカーの
  grant 時だけでなく**実アダプタ境界でもう一度確認**する。
- `target_ref` は**新規スコープ**を指す意味に限定し、既存 Pod を指さない。retained Pod の
  扱いは別定義が必要。
- キャンセル時は「作成結果不明(create unknown)」を照合し、**該当 Pod の削除と不在を
  正確に確認**する。`bytearray` のワイプは Pod を削除しない。
- role の不足: ブローカーは operation ごとに値 1 個。実経路は management key と 5 role を
  別々に読むため、役割別の保管・読み出し設計が未定。
- 型付き受け渡しの不足: fake の `secret_reader` は `bytearray` の抽象のままで、実 provider が
  期待する `str` と署名鍵の hex デコードを通らない。fake をそのまま実経路に差し替えることは
  できず、`bytearray` → `str` の変換点(ワイプできないコピーが生じる箇所)の設計が未定。

## 3. Mattermost 対応付け(現状の記述と将来の境界)

> **確認者の区別**: 同じく Codex が既存の不変ソース
> (`native_supervisor.py` と `native_service.py`)を独立に読んで照合したもの。作成者(Claude)は読んでいない。

現行経路:

- `Start-NativeEventTrial.ps1` → `native_supervisor_entry` → `native_supervisor.main`。
- 現状、hidden な鍵入力は **CLI の内部**で行われ、注入鍵やキャンセルコンテキストを受け取る
  引数は**ない**。
- `CONTROL_PLANE_API_KEY` を子プロセスの環境変数へ渡す。「メモリのみ」は**ディスクに書かない**
  という意味であり、**環境変数を使わないという意味ではない**。
- 準備 300 秒、別枠で監視 300 秒 + キャンセル猶予 32 秒、最大 60 reads / 5 events。
- 停止時: ChildJob 停止 + 環境変数クリア + SQL の protected クリーンアップ。
  **課金ハードキャップは未検証**。
- 別 RPC / `service.finish` 側のクリーンアップは別物で、維持が必要。

モックとの対応:

| 実経路 | モック | 差分 |
|---|---|---|
| 準備(≤300 秒) | `prepare()` + `MM_PREPARATION_CAP` | 待機なし。上限は協調チェックのみ |
| 監視(≤300 秒、別枠) | `monitor()` + `MM_MONITOR_CAP` | 準備とは別フェーズ。合計 300 秒とは扱わない |
| 60 reads / 5 events | `MM_MAX_READS` / `MM_MAX_EVENTS` | 合成カウンタ |
| キャンセル猶予 32 秒 | 未モデル化 | |
| ChildJob 停止 / env クリア / SQL protected | `active_zero` / `protected_zero` | 合成カウント。プロセスも env も SQL も触らない |
| 子への env 受け渡し | なし | モックは子プロセスを作らない |

接続前に必要なこと(未実装):

- 既存スクリプトは変更しない。注入コンテキストと固定の子プロセス転送路は、**別途レビュー
  された変更**として後日追加する。`getpass` の monkeypatch や subprocess の argv 渡しを
  安全な代替と見なさない。
- PR31 の `BoundedMockBroker` は MM の期限を **grant 時点から 300 秒**で切る。これは
  「準備 300 秒 + 監視 300 秒 + 猶予」の全ライフサイクルを表現できない。実束縛の前に
  **フェーズ単位のポリシー**(phase-bound policy)が必要。

## 4. 未設定・未検証の項目

- 実 Win32 への保存は行っていない。`WindowsCredentialStore` は既定無効のままで、今回の
  コードから生成も呼び出しもしない。
- 保持期間(retention)、ACL、サービス化、ネットワーク設定は未定義・未設定。
- 永続台帳なし。プロセス再起動で grant・再利用防止状態は消える。
- role の不足(§2)、MM のフェーズ期限(§3)、アダプタ束縛の欠如(§1)。
- クリーンアップの区別: (a) メモリ上コピーのワイプ、(b) ストア削除、(c) journal close、
  (d) Pod 削除と不在確認、(e) MM の ChildJob / env / SQL protected、(f) 別 RPC /
  `service.finish`。今回扱うのは (a)(b) の実処理と (c)(d)(e) の合成フラグのみ。

## 5. テスト

実プロセス・ファイル・ネットワーク・OS Credential API・実 hidden プロンプトは使わない。
テストは `orchestrator` を読むためにリポジトリルートを明示的に `sys.path` へ追加する
(`-I` では cwd とスクリプトのディレクトリが入らないため)。

```
C:\path\to\python.exe -I -B C:\path\to\checkout\docs\examples\local-credential-broker\launcher-bridge-mock.test.py
```

実行記録:

- 履歴: Codex がレビューのうえ初回実行、当初の 6 テスト PASS(0.003 秒)。
- **最終確認(Codex 実行): 全 9 テスト PASS(0.004 秒)**。内訳は当初の 6 件 + レビュー指摘で
  追加した 3 件。実行待ちのテストはない。
- **既定 CLI(フラグなし)も Codex が実行**: `disabled` を出力して終了コード 0、プロンプトなし。
- 作成者(Claude)はシェルを使っておらず、自分ではテストを実行していない(机上確認のみ)。

この 9 件の証跡は**モックのみ**である。live の資格情報受け渡しは行っておらず、実クリーンアップ
(実 Pod 削除・実課金停止など)の保証にもならない(§1)。

当初の対象(6 件): 既定 OFF でプロンプトなし / 登録 1 回で 2 operation を別承認で実行 /
不正入力は下流に届かない / 再利用・期限切れ・タスク違いの拒否 / fake 失敗時もクリーンアップ
実行、例外・fixture・ハンドルが出力に出ない / 削除後はストア利用不可。

追加した対象(3 件、実行済み):

- fake ライフサイクル中の期限到達: ブローカーが受理した後、fake の `run_injected` の前に
  fixture の時計を `approval.deadline` まで進める(テスト内だけで固定プレースホルダ reader を
  差し替える。本体コードとブローカーは変更しない)。結果は `expired`、クリーンアップは
  `journal_closed` と `pod_absent` の両方が真。
- 合成値以外の owner 入力: fake にも下流にも届かず、出力は安全な status のみ。
- hidden コールバックの例外: 同上。例外文字列は出力に出ない。

後の 2 件のテストは登録結果を `denied` または `failed` のどちらかとして受け入れる。Codex の
ソース照合によれば、実際に返るのは合成値以外の入力で `denied`、hidden コールバックの例外で
`failed`。

手動デモ(対話端末のみ、`synthetic-fixture` 以外は拒否):

```
C:\path\to\python.exe -I -B C:\path\to\checkout\docs\examples\local-credential-broker\launcher-bridge-mock.py --mock-enabled
```

公開オプションは `--mock-enabled` のみ。live フラグはない。

## 6. 戻し方と、将来の所有者確認の最小項目

戻し方: 上記 3 ファイルを削除する(またはブランチを破棄する)。既存ファイルへの変更、
永続データ、OS 側の保存はないので、他に戻す対象はない。

実束縛を検討する前に所有者が最低限確認すること:

1. このブランチのベースが PR31 の上記 head のままか。
2. §2・§3 の実ランチャー記述が現物と一致するか(Codex は照合済み、作成者は未読)。
   あわせて `bytearray` → `str` / hex の型付き受け渡しをどこで行うか。
3. アダプタ登録フックをどう追加するか(PR31 への変更は別承認・別レビュー)。
4. 実アダプタ境界での承認再確認(deadline / budget / target_ref / plan_digest)と、
   `target_ref` = 新規スコープの定義。
5. RunPod: create unknown の照合と Pod 不在確認の手順、プロバイダ側ハードキャップが
   ない前提での費用上限。
6. MM: 注入コンテキスト / 固定子転送路の設計、env 経由の露出の扱い、フェーズ単位期限、
   課金上限の検証。
7. 身元認証(同一プロセス・同一ユーザーのコードを防げない点)と OS レベル隔離の要否。
8. Win32 保存を有効化する場合の保持期間・ACL・削除手順。

## 7. PR31/32 interfaceレビューでの補正

- 既存CIはmain/phaseだけを対象にしていたため、PR32のstacked baseでは起動しなかった。
  PR32内で対象baseを追加し、12件のbridge unittestと既定OFF CLIをUbuntu/Windowsで実行する。
- MM fake lifecycleの総期限もgrant時点+300秒と元承認期限の早い方にそろえた。
  prepareの300秒とmonitorの300秒は別phaseの上限であり、合計300秒を本来の
  lifecycle仕様だとは扱わない。ただし現PR31は総期限300秒という保守的な制限のため、
  fakeのphaseもその総期限内に収める。準備300+監視300+猶予32秒をliveで実現する
  phase policyは未実装で、ここで承認範囲を延長しない。
- broker preflight中のcancelをfake開始時のEvent再作成で取り消さないよう補正。
- 5role名とstr/hex型の不足は既存説明どおり。1個のmock値を共有することは、実5roleを
  一つのキーに置き換えてよいという意味ではない。役割ごとの登録・保持方針は別途確認。
- 追加テストは総期限/元期限の継承、prepareとmonitorの別phase、
  preflight中のcancel維持。実秘密、実Win32、実launcherは使わない。
