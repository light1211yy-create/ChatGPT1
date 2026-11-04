# WindowsでのPhase 1・Phase 2動作確認

対象：Windows、Python 3.12／64bit。今回のクラウドQAはLinuxであり、この手順のWindows実機実行は未検証。Phase 1の起動成功については以前のユーザー報告があるが、Phase 2全機能の合格を意味しない。

## 1. 準備とデータの隔離

1. GitHubの`main`（検証基準`ee915c21b1933b9d3044eb583bfe2853fa8bda62`）のソースを、実運用フォルダとは別のQA用フォルダへ展開する。GitHubのソースにはユーザーDBや`.venv`は含まれない。今回のQA ZIPの`qa`と`docs`も追加する。
2. 実データ・`.env`・秘密設定・許諾書はコピーしない。新しいQA用フォルダでのみ`setup_windows.bat`を実行する。既存の実運用環境の仮想環境を再設定しない。
3. セットアップがPython 3.12／64bitを確認し、`Setup completed`と表示することを確認する。管理者権限や証明書検証の無効化は不要。エラー時は処理が止まり、ウィンドウに案内が残ることを確認する。
4. QA用フォルダでPowerShellを開き、次を実行する。`$HOME`等のシステム変数は変更しない。

```powershell
$qaDataDir = Join-Path $env:TEMP ("makase-qa-" + [guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $qaDataDir | Out-Null
$qaHadDbSetting = Test-Path Env:MAKASE_DB_PATH
$qaPreviousDbSetting = $env:MAKASE_DB_PATH
$env:MAKASE_DB_PATH = Join-Path $qaDataDir 'manual.sqlite3'
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -c "import struct; print(struct.calcsize('P') * 8)"
.\.venv\Scripts\python.exe -m pip check
```

期待値はPython 3.12系、64、`No broken requirements found`。一時DBの環境変数はこのPowerShellから起動したプロセスにだけ引き継がれる。**この後Explorerでバッチをダブルクリックしないこと。** 別プロセスでは一時DBの設定を引き継がず、既定の保存先を使う可能性がある。

## 2. 自動テスト

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q --junitxml="$qaDataDir\existing.xml"
.\.venv\Scripts\python.exe -m pytest -q qa\test_phase12_qa.py --junitxml="$qaDataDir\qa.xml"
```

- GitHub基準コミットには44件の既存テストがある。クラウド作業ツリーでは、未pushのCodex検証用27件を含む既存71件を実行した。取得したファイルによって件数が異なるので、実行対象と件数を記録する。
- 追加QAは33件。今回のLinux実行では29成功・4失敗。失敗は既知のQA-01（2件）、QA-02、QA-03を検出する通常のテストであり、xfailやskipで成功に置き換えていない。修正前にこれらが失敗することは報告済みだが、Windowsで同じ結果になるかは実測する。
- どちらのテストも一時DBを使う。Codex検証用テストはモックであり、実AI接続・認証・課金操作を行わない。

## 3. バッチとローカルポート

8501番を使う既存アプリがないことを確認してから、**同じPowerShell**で次を実行する。

```powershell
.\start_windows.bat
```

ブラウザが開き、日本語のMAKASE画面が表示されることを確認する。自動で開かなければ起動ウィンドウのアドレスを入力する。データは上で指定した一時DBに保存される。実運用の`data`フォルダを開いて操作しない。

8501番が使われている場合は他のプロセスを停止せず、バッチのポート使用中の案内を確認する。画面確認には次の別ポートを使う。

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 18501 --server.headless false --browser.gatherUsageStats false
```

18501番も使用中なら別の空きポートを選ぶ。外部公開するアドレスは指定しない。終了は`Ctrl+C`。以下の確認では、必ずQA用サーバーを開いていることを確認する。

## 4. 画面での確認項目

| 操作 | 期待値 |
| --- | --- |
| 空のダッシュボードを表示 | テーマ・承認待ち・制作中・投稿済みがすべて0 |
| 全5メニューを切り替える | 日本語の見出しと入力欄が表示され、例外がない |
| 企画対象日・重点ジャンルで10案作成 | 10件、参考スコア、理由、構成。「AI未接続」の表示あり |
| 同じ条件でもう一度作成 | 別の企画履歴に10件追加され、元の10件が残る |
| テーマを修正・承認・却下 | 入力した内容・状態・履歴が保存される |
| 承認テーマの進捗を「編集」、別の1件を「投稿済み」へ | ダッシュボード件数と進捗一覧に反映される |
| 投稿実績を登録 | タイトル・ジャンル・再生・いいね・保存が残る |
| いいね数を再生数より大きくして登録 | エラーとなり保存されない。正常値に直して登録できる |
| 承認テーマに施設A/Bを登録 | 名前・住所・公式URL・施設情報・料金条件・確認日が保存され、比較表に2件出る |
| 施設情報を編集 | 最新値が表示され、別テーマの候補と混在しない |
| 出典を登録・修正 | 項目・確認情報・URL・確認日が保存される |
| `javascript:`等の出典URLを保存 | エラーとなり保存されない |
| 未来の出典確認日を指定 | 日付UIで制限される。保存処理でも拒否される |
| 写真候補を未確認で登録 | 参照URLが保存されるが利用可の件数に含まれない |
| 根拠等が空のまま「利用可」で保存 | エラーとなり保存されない |
| 権利者・根拠・用途・クレジット・期限を入れる | 入力値が残り、期限内のみ利用可と扱われる |
| 過去の期限で「期限切れ」として登録 | 候補は残るが利用可に数えない |
| テーマの承認を取り消す | 制作進捗は未着手へ戻り、施設情報は閲覧専用。再承認で編集可能 |
| サーバー停止・同じPowerShellから再起動 | テーマ・承認履歴・進捗・実績・施設・出典・写真情報が残る |

確認日や写真の期限について、PCの日付は変更しない。期限当日／翌日の厳密な判定は一時DBの自動テストで確認する。

日本語の文字化け・フォント、画面幅、長い文章・住所、Windowsの空白や日本語を含むフォルダ、ブラウザ自動起動、ファイアウォールやポート競合は実機で確認し、結果を記録する。

## 5. 実サーバーを使う自動確認

```powershell
.\.venv\Scripts\python.exe qa\live_server_check.py
```

自分専用の一時DB・空きポートでサーバーを起動し、HTTPとWebSocketから5画面の遷移・ボタン操作・保存・サーバー再起動後の保持を確認する。終了時はこの処理が起動したサーバーだけを停止する。既存のサーバー・実DBは変更しない。クラウドでは成功済みだが、Windowsでは未検証。実ブラウザのフォントや画面レイアウトの確認の代わりにはならない。

## 6. 既知問題の再現

- QA-01：別々のタブで同じテーマ（または施設）を開く。タブBで内容を変更・保存し、その後タブAの古い画面から保存する。最新の保存済み値は保護されるが、タブAで保存不可の警告が出ず、編集中の値が消えることがある。保存完了の表示と実際の一覧値を確認する。
- QA-02／QA-03：通常UIが制限する未来日・真偽値について、保存層には不足がある。追加QAの該当テストを一時DBで実行する。実DBへ直接データを投入しない。

## 7. 終了

QAサーバーが停止した後、同じPowerShellで環境変数を元に戻す。

```powershell
if ($qaHadDbSetting) {
    $env:MAKASE_DB_PATH = $qaPreviousDbSetting
} else {
    Remove-Item Env:MAKASE_DB_PATH -ErrorAction SilentlyContinue
}
```

一時DBと結果XMLは証跡として残せる。実運用データを削除・復元・上書きする操作はこの確認には不要。失敗した場合は、環境・操作・期待値・実際の表示・テスト名を記録し、認証情報や個人データを共有しない。
