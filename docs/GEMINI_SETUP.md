# Geminiテーマ生成：導入・課金条件・検証状況
## Gemini 3.8 Flash への更新（2026-11-09、ブランチ検証中）

モデルIDは `gemini-3.8-flash`、Gemini AIモードの既定思考設定は `thinking_level=MEDIUM` です。`thinking_budget` と `candidate_count` は送信しません。従来の `gemini-3.5-flash-lite` はユーザーが明示選択できる候補として残し、自動フォールバックは行いません。

Google公式の[3.8 Flash仕様](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash)、[料金表](https://ai.google.dev/gemini-api/docs/pricing)、[移行ガイド](https://ai.google.dev/gemini-api/docs/latest-model)を参照。料金表ではStandardのテキスト入力・出力にFree tier枠がありますが、実際のキー／プロジェクトで利用できること、残り枠、請求先無効は別途本人が確認してください。

API通信・実キーの読み出しは行っていません。従来の `google-genai==3.0.0` を維持していますが、Gemini 3.8本体との互換性や実際の生成成功は未確認です。初回送信にはユーザーの別途明示承認が必要です。既存SQLite・`data`・`.streamlit/secrets.toml` を削除、上書きしないでください。

この追記より前の「3.5が唯一」「3.5が最新」という記述は旧版の履歴です。最新の構成は本節と `studio/gemini_models.py` を優先してください。


更新日：2026-11-09（日本時間）。今回の基準コミット11b46c6。ユーザーが確認したGoogle公式情報を根拠に3.5を登録した。Codexによる直接取得・実API確認ではない。初回実API試験は別途承認待ちで、今回の開発では通信・実キーの読み出し／表示／送信を行わない。

## 1. 無料枠の確認状況とモデル

登録根拠はユーザー側での公式確認。確認者・日付・出典をモデル設定へ記録し、Codex自身の直接確認とは区別する。詳細は[確認記録](GEMINI_MODEL_REVIEW.md)を参照。

| 候補モデル | アプリでの扱い | 現在の料金確認 |
| --- | --- | --- |
| `gemini-3.5-flash-lite` | Geminiモードの既定・唯一の選択肢 | ユーザーが安定版ID、Standard Free tierテキスト入出力、JSON出力、Thinking各levelを公式確認 |
| 旧`gemini-2.5-flash-lite`／`gemini-2.5-flash` | 現在は選択・送信不可 | 現在の提供状況・新規Free tier資格・互換性を未確認 |

根拠は[モデル仕様](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite)、[料金表](https://ai.google.dev/gemini-api/docs/pricing)、[Thinking仕様](https://ai.google.dev/gemini-api/docs/generate-content/thinking)。前回のCodex調査は環境プロキシで403だったが、今回ユーザーが公式確認情報を提供したため登録した。Codexが直接ページを取得できたとは報告しない。本人はFree tier・請求先未設定を確認済みで、キーと対象プロジェクトの対応は初回通信前に再確認する。実キーやsecrets.tomlは今回開いていない。

SDKは`google-genai==3.0.0`を維持する。Thinkingは`ThinkingConfig(thinking_level=ThinkingLevel.MINIMAL)`相当を使用し、`thinking_budget`は設定・送信しない。対応する型・構造化JSON設定・実際にシリアライズされるリクエストをMockTransportで検査する。`max_output_tokens=8192`はアプリ側の出力上限であり、公式最大値を確認したという意味ではない。SDK版違い・未登録モデル・不正な確認記録は送信前に拒否する。実サーバーの互換性・品質・利用枠は初回試験まで未検証。

Google AI Pro、GeminiアプリのPro、Antigravityの利用と、Gemini Developer APIの課金は別。契約を無料APIの利用権と扱わない。

## 2. 本人が確認すること（送信前の必須条件）

1. [Google AI Studio](https://aistudio.google.com/)でAPIキーに対応するプロジェクトIDを確認する。別のキーやプロジェクトの画面を根拠にしない。
2. 選択するモデルのFree tierが、現在の公式料金表と自分の地域・プロジェクトで利用可能であることを確認する。検索grounding・バッチ・キャッシュ等の別機能を無料だと仮定しない。
3. プロジェクトがFree tierであることを確認する。Google CloudのBilling画面でも、そのプロジェクトが課金アカウントにリンクされておらず、Billingが無効であることを確認する。
4. 既に課金有効のプロジェクトや、課金を有効にした無料トライアル残高のあるプロジェクトのキーは使わない。予算アラートを0円の強制上限とみなさない。
5. キーにGemini Developer API向けの適切な制限を設定する。アプリが設定やプロジェクトを変更・アップグレード・課金有効化する機能はない。既存の別サービス用プロジェクトの設定を本検証のために勝手に変更しない。
6. これらを確認できない場合はGeminiの確認チェックを入れず、送信しない。モデルが廃止・有料化されていたら、この実装が別モデルへ自動切り替えすることはない。

**アプリはAPIキーだけからCloud Billingの状態や無料利用資格を検証できない。** チェックは本人による申告であり、課金状態の技術的保証ではない。課金有効キーを誤って使えば、この実装が料金発生を防げる保証はない。状態が変わる可能性もあるため、使用時に本人が確認する。追加費用0円を維持できない設定では使わない。

参考：[Billing](https://ai.google.dev/gemini-api/docs/billing)、[Rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)、[API keys](https://ai.google.dev/gemini-api/docs/api-key)。操作画面の項目は更新される可能性があるため、公式説明とプロジェクトIDを照合する。今回これらの現行本文は確認できていない。

## 3. Windows・GitHub Desktopで更新する

1. MAKASEを停止し、ソースと実DB・関連ファイルをバックアップする。`MAKASE_DB_PATH`指定時はその保存先も含む。
2. GitHub Desktopでローカル変更を確認する。未保存の変更をDiscardしない。今回の変更がpush承認・反映された後にFetch origin → Pull originで取得する。push前はFetchしても新機能は届かない。
3. 既存プロジェクトで次を実行する。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

今回は依存変更なし。既に公式SDK `google-genai==3.0.0`を導入済みならpipの再実行は不要で、Fetch／Pullによるソース更新でよい。上記コマンドは未導入・版違いの修復時に使う。Python 3.12／64bitを使用する。TLS証明書検証を無効にしない。`start_windows.bat`・DBスキーマは変更していないため、再作成やDB初期化は不要。

### `cannot import name 'genai' from 'google'`が出た場合

起動に使った仮想環境で`google-genai`を読み込めない状態。ソースのPull／ZIP更新だけでは既存`.venv`の依存は更新されない。アプリを停止し、`app.py`と同じフォルダの`setup_windows.bat`を再実行するか、上記の`.venv`を明示したpipコマンドを実行する。`google`や旧SDKの`google-generativeai`を代わりにインストールしない。`data`や`.venv`の削除は不要。

同じフォルダで次を実行し、API通信せずにインストールを確認できる。

```powershell
.\.venv\Scripts\python.exe -c "from google import genai; from importlib.metadata import version; print(version('google-genai'))"
```

SDKとキーは、3つの確認・承認が揃った生成時だけ読み込む。画面の表示・モード変更・送信内容のプレビュー・未承認の生成操作ではキーを読まない。SDK未導入でも無料テストモードは動作する。本人から`Gemini SDK OK`の表示報告はあるが、今回の更新全体のWindows実機確認は未実施。

## 4. APIキーを安全に設定する

キーをチャット・GitHub・画面の企画メモへ貼り付けない。アプリは`GEMINI_API_KEY`だけを読み、別プロジェクトの可能性がある`GOOGLE_API_KEY`へはフォールバックしない。画面からキーを入力・表示・保存する機能はない。

### 方法A：Git管理外のStreamlit秘密設定

既存の`.streamlit/secrets.toml`があれば他の値を保持し、トップレベル（他のセクションより前）に以下のキーを置く。実際の値は自分のPCのエディタで入力する。

```toml
GEMINI_API_KEY = ""
```

空欄のままでは送信できない。ファイルを作成するなら通常のローカルエディタを使う。`.env`は自動で読み込まない。

```powershell
git check-ignore .streamlit/secrets.toml
git ls-files .streamlit/secrets.toml
```

最初のコマンドで除外パスが表示され、2番目は空であることを確認する。既に追跡されていたら送信を止め、秘密を表示せずGit管理状態を直す。キーを含むスクリーンショットや差分を共有しない。

### 方法B：現在のPowerShellの環境変数

コマンド履歴へキーを直接書かないため、対話入力で受け取り、同じPowerShellからバッチを起動する。

```powershell
$makaseGeminiKey = Read-Host 'GEMINI_API_KEYを入力' -AsSecureString
$env:GEMINI_API_KEY = [System.Net.NetworkCredential]::new('', $makaseGeminiKey).Password
Remove-Variable makaseGeminiKey
.\start_windows.bat
```

環境変数の値を表示しない。ExplorerのダブルクリックはこのPowerShellの変数を引き継がない場合がある。終了後は必要に応じて`Remove-Item Env:GEMINI_API_KEY`でそのセッションの変数を消す。環境変数と秘密設定の両方にあれば環境変数を優先する。

## 5. 実AIで10テーマを生成する方法（確認・承認後に1回）

**モデルは選択可能だが、初回実API試験は別途承認待ち。** 以下は将来その承認後に本人が行う手順。今回の開発許可を実通信の承認として流用しない。3つ目のチェックでも「初回実APIテストは別途承認済み」を確認する。承認前はチェック・送信しない。

1. 起動直後は無料テストモードであることを確認する。ここではAPIへ通信しない。
2. 「AI投稿テーマ企画」でGemini AIモードを明示選択する。既定の`gemini-3.5-flash-lite`と、ユーザー確認情報を根拠とする説明を確認する。ここまでキーは読み取らない。
3. 企画対象日・重点ジャンル・メモを入力する。「送信内容を更新して確認」で、実際に外部へ送る内容を確認する。フォームの値をその後変えた場合は、もう一度確認する。
4. **実際に設定されたAPIキーが、確認済みのFree tier・請求先未設定プロジェクトに対応することをGoogle AI Studioで本人が再確認する。** キーの値をチャットや画面に表示しない。モデルの無料枠、Billing無効とメモ・テーマ名に秘密情報／個人情報がないことも確認する。
5. 3つの確認・承認をチェックし、「テーマ10案を作成」を**1回だけ**押す。開発者がクラウドで試験する場合は、この操作とは別に本人が無料枠・認証設定を確認して明示承認し、キーは環境設定の秘密欄等で安全に設定する。キーをチャットへ送らない。
6. 成功したら10件と生成モデル・日時を確認する。`AI提案（最新Web情報・施設情報は未確認）`の表示を確認し、従来どおり修正・承認・却下する。失敗したら停止し、結果を成功扱いにしない。

確認・承認は試行ごとにリセットする。失敗時にも再承認が必要。429は利用枠不足として停止し、自動再試行・追加モデル・有料APIへ切り替えない。通信のHTTPタイムアウトは30秒。SDKの試行回数は1で、ストリーミング・検索・grounding・外部ツール・ファイルアップロードは使わない。無料枠の日次値などを古い固定値で保証しない。

環境設定の変更・APIホストへのアクセス確認は今回行っていない。クラウドとWindows PCの通信・認証設定は別であり、Windowsのキーをクラウドで利用できるとは仮定しない。実API試験は別の明示承認まで行わない。

## 6. 送信・保存する情報

- 有効化後の送信対象：企画対象日、季節、例年の祝日・月別イベントのヒント、マカセの固定プロフィール、ホテル5選・レストラン5選・旅行／おでかけ5選の企画形式、重点ジャンル、メモ、ジャンル別実績集計、直近300件までのテーマ名。5選は後で出典を確認して施設を選ぶ形式であり、未調査の施設・価格を埋める指示ではない。プロンプト版は`makase-gemini-v2`。
- 送信しないもの：投稿実績の個別タイトル・ID・投稿日・メモ、写真権利資料、画像、承認履歴、DB全体、APIキーを含むプロンプト。
- メモや生成テーマ名に個人情報が入っていれば、それも送信対象になり得るため本人が除く。一般的なキー・メール・電話番号等のパターンを送信前に拒否するが、全ての名前や個人情報を自動識別する保証はない。
- Google側の無料枠のデータ取扱い・保持・改善利用条件も、本人が最新の規約で確認する。個人情報・秘密情報を送らない。
- ホテル・旅行は「おでかけ」、レストランは「グルメ」。既存カテゴリー体系は維持し、従来のテスト生成は従来の5カテゴリーで動く。
- 返答は`title/category/score/reason/outline`の10件JSON。形式、文字数、整数スコア、件数、空欄、カテゴリー、重複を検証する。最新トレンド、実在施設・料金・イベント開催を確認したという意味ではない。
- 過去の全保存タイトルとは、空白・全半角・英字大小文字を正規化して重複を拒否する。古い300件より前のテーマもローカル判定対象。意味が似ているが表記の違うテーマの判定は人による確認が必要。
- 同時生成の競合にも備え、保存トランザクション内で全既存タイトルを再検査する。従来テストモードの同条件再生成は既存どおり許可する。
- 生成元モデル・プロンプト版は既存`batches.provider`、生成日時は`batches.created_at`に保存する。新しいテーブル・マイグレーションは不要。キー・生のAPIエラー・HTTPログは保存しない。HTTPのwire/debugログを有効化しない。

## 7. テスト・実機確認の区別

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q tests qa\test_phase12_qa.py
```

既存226件を保持し、3.5の登録・SDK送信形式・承認前のキー未読み出し・失敗時の無保存等28件を追加した。旧モデルのテストは架空の確認記録、モデル未登録のテストは空の一覧を明示し、元の期待値を維持する。3.5のテストは実際の登録設定と公式SDKを使うが、キーはダミー、通信はMockTransportで、実Google APIへは送信しない。

今回のテスト環境はLinux・Python 3.12。254件成功・失敗／スキップ0件。一時DBだけを使用し、実API試験や実キーの読み取りは行わない。3.5の成功応答もモック結果として扱う。

確認内容：キー未設定、無料枠／Billing／送信承認の不足、不許可モデル、401/403、429、タイムアウト、その他エラー、不正JSON・件数・重複、途中失敗・無保存、同時保存時の重複再検査、モード切替、モデルと日時の記録、生成案の承認・修正・却下、従来モードの継続。

実サーバーの5画面・保存・再起動後の保持も成功。Chromiumでは3.5の既定表示、ユーザー確認という出所、3確認不足時の停止・確認リセット、無料テストモードへの復帰を確認した。ブラウザ試験ではキー読み取り関数を禁止し、ブラウザの外向き通信を遮断した。前回までの記録はGEMINI_MODEL_REVIEW.mdの履歴として保持する。

実APIを自動で呼ぶテストは追加していない。実モデルの日本語品質・対象キー／プロジェクトの利用資格・利用枠・遅延・サーバー側の設定受理、今回のWindows実機動作は未検証。

## 8. 実装範囲

今回の範囲はテーマ生成と安全な保存まで。施設自動調査、写真ダウンロード、Canva編集、TikTokへの転送・投稿、定期スケジュール、有料プランへの登録・アップグレードは実装・実行しない。GitHubへのpushは、ローカルコミットと送信対象を提示して本人承認後に行う。
