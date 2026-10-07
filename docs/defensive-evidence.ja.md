# 防御検証の証拠台帳

Experimental / MANUAL_ONLYを維持します。受付側と候補検証側に共通のJUnit構造検証を導入しました。報告を作ったworkerが実際にテストを実行した証明にはなりません。

| 主張 | テストまたは原本 | コマンド | 実測結果 | 限界 |
| --- | --- | --- | --- | --- |
| 旧候補パーサーの4種類の誤受理を再現 | `evidence/junit-baseline.json`、`test_junit_validation.py`の対応入力 | base commitで`IndependentVerifier.parse_junit_xml`を4入力に適用 | failure要素との矛盾、全件skip、不正件数、件数のみの入力が全てtrue | 合成入力によるローカル再現 |
| 矛盾や全件skipを拒否し、実際のtestcaseと結果要素を数える | `tests/unit/test_junit_validation.py`、`test_handoff.py`、`orchestrator/core/junit.py` | 英語版のfocused command | 93 passed、2 skipped、51 subtests passed | 構造整合性の検証。報告の真正性は別途必要 |
| ネストした集計を二重加算しない | nested countsとaggregateなしfailureの回帰テスト | 同上 | 成功 | UTF-8、名前空間なし、件数は非負ASCII整数10桁までの対応形式 |
| サイズと構造上限、DTD拒否を適用 | byte boundary、node/depth、encoding、hierarchy、DTD回帰テスト | 同上 | 成功 | 10 MiB、100000要素、深さ64。上限テストは小さい設定値による境界確認で、負荷試験ではない |
| 収集から欠落したパスの削除はdiffに結び付かない | `test_missing_collected_path_is_not_deletion_evidence`、`compute_diff`の説明 | 同上 | baselineだけのパスはchangedに含まれず、比較フラグはtrue | 限界の再現のみ。削除を含む完全なdiffの証明として扱わない。修正範囲は広げていない |
| 通常テストの互換性を確認 | `evidence/defensive-local-verification.json` | 英語版の全テストコマンド | 277 passed、2 skipped、51 subtests passed | Windows junction fixtureの2件をLinux環境のためskip。実Docker境界2ファイルを除外。Windows実行は未実施 |
| 静的検査と秘密パターン検査 | 同じ検証記録 | `python -m ruff check orchestrator tests scripts`、`python scripts/secret_scan.py` | 両方exit 0 | 網羅的秘密監査ではない。依存関係監査の再実行なし |

受付ツールの到達状態はCOLLECTEDのままです。workerの成功申告や文字列ヒューリスティックの「ok」を独立したセキュリティ受入証拠にしません。整合する偽のJUnit報告は構造検証を通り得るため、信頼できる実行と由来の確認が必要です。件数だけの報告は新たに拒否するため、既存の成功用fixtureには実際のtestcaseを追加しました。

## 再現とリビジョン

基点commitは`4fb014a4ac91fd042b4797c10bd568e5f76880b5`、実装とテスト証拠のcommitは`2765dc2e3c649b61386fe50193024996c9458f56`です。いずれもこの変更はローカル限定で、続くcommitに文書を含めています。追加変更のCIは未実行で、以前のgreen CIを新しいテストの証拠にしていません。pushもmergeもしていません。

宣言された依存関係を隔離したWSL Ubuntu 24.04のPython 3.12環境で、各リポジトリのルートから実行しました。[実測記録](../evidence/defensive-local-verification.json)に正確なコマンド、出力、UTC日時、検証対象PythonファイルのSHA-256があります。`git log -2 --oneline`でローカル2commitを確認できます。実行モデルとeffortの設定は独立確認できず、Astra mediumで実行したとは主張しません。
