# Gemini最新モデル：公式資料の調査・調整記録

調査日：2026-11-08（日本時間）。基準コミット75981be。実API通信0回。モデル一覧のAPI照会も行っていない。本人のsecrets.toml・キーは開かず、課金・アカウント・ネットワーク設定は変更していない。

## 調査結果と採用判断

**採用モデルなし。** 第一候補`gemini-3.5-flash-lite`は、正式ID・新規Free tier資格・テキスト入出力の無料枠・モデル固有設定を公式資料で確認できていないため、選択肢へ追加していない。旧2.5も現行の提供状況と利用資格が未確認で、現在は選択・送信不可。これはGoogleの提供停止を確認したという意味ではない。

本人からFree tier・請求先未設定・Windowsの`Gemini SDK OK`の報告はある。これらと、モデル側の最新の利用資格・料金・設定は別に確認する。APIキーだけでBilling状態は検証できず、今後も本人による確認を必須とする。

## 公式資料へのアクセス記録

| 指定資料 | 確認する内容 | 結果 |
| --- | --- | --- |
| [Models](https://ai.google.dev/gemini-api/docs/models) | 正式ID・提供状況・モデル制限 | プロキシのCONNECTで403、本文未取得 |
| [Pricing](https://ai.google.dev/gemini-api/docs/pricing) | テキスト入出力の無料枠・新規プロジェクト資格 | 同上 |
| [Thinking](https://ai.google.dev/gemini-api/docs/thinking) | モデル別level／budget・許可値 | 同上 |
| [Structured output](https://ai.google.dev/gemini-api/docs/structured-output) | モデル別JSON schema対応と制限 | 同上 |
| [Rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) | 現行利用枠・地域やプロジェクトの制限 | 同上 |

通常サンドボックスでは接続不可だったため、継承した環境プロキシで同じ5 URLを再確認した。すべて`Tunnel connection failed: 403 Forbidden`。この403は環境プロキシによる拒否で、Googleのモデル提供状況を示さない。アクセス制限を回避せず、本文・価格・上限の数値を推測していない。

後続調査には公開資料ホスト`ai.google.dev`を読める環境が必要。資料の確認だけなら、Gemini APIホストへのアクセスやキーは不要。今回は環境設定を変更していない。

## 第一候補の未確認項目

| 項目 | 現在の結論 |
| --- | --- |
| `gemini-3.5-flash-lite`という正式ID・提供継続 | 未確認。設定しない |
| 新規Free tierプロジェクトでの利用資格 | 未確認 |
| テキスト入出力の無料枠 | 未確認 |
| 構造化JSON出力 | 実モデル対応は未確認 |
| Thinking方式・対応するlevel等 | 未確認。旧2.5設定を流用しない |
| google-genaiとの実モデル互換性 | 未確認 |
| 出力上限・現在の利用枠・地域制限 | 未確認。数値を固定して保証しない |

## 実装した調整

- 公式確認済みモデルの一覧とモデル別設定を`studio/gemini_models.py`へ分離した。現在の登録は0件。環境変数や秘密設定から任意モデルを登録する機能はない。
- 確認済みモデルがない場合はモデル選択・Gemini生成ボタンを無効にし、サーバー側でも送信を拒否する。3つの確認チェックは残すが、未確認モデルの有効化には使えない。
- 将来の登録では、正式ID、新規Free tierの利用資格、無料テキスト入出力、構造化JSON、Thinking方式と最大出力、SDKとの組み合わせを公式情報で確認し、出典5 URLと確認日を記録する。記録の形だけで料金が証明されるわけではなく、レビュー担当者の公式確認が必要。
- Thinkingのlevelとbudgetを排他的に扱い、出力数もモデル別にする。設定不正・SDK版違い・生成準備後の確認取り消し／設定変更では送信しない。自動再試行・別モデルへの自動切り替えはない。
- 404では提供状況・プロジェクト資格の確認を日本語で案内し、別モデルへ切り替えない。既存の認証エラー・429・タイムアウト処理も維持する。
- 投稿形式はホテル5選・レストラン5選・旅行／おでかけ5選を明示。施設名・価格を創作して5件埋めず、後で出典を調べて施設を選定する企画形式とした。プロンプト版は`makase-gemini-v2`。
- ThemeDraft・JSON10件・重複拒否・承認／修正／却下・既存SQLite保存は維持。DB・Windowsバッチ・依存ファイルは変更しない。

## SDK側で確認できたこと

インストール済み公式SDK`google-genai==3.0.0`に、`ThinkingConfig.thinking_level`、`thinking_budget`、`GenerateContentConfig.response_json_schema`があることをローカルで確認した。SDKのlevel型はMINIMAL／LOW／MEDIUM／HIGHを表現できる。これは各モデルが全ての値を受け付けるという証明ではない。

公式SDKをMockTransportへ接続し、架空のモデルに対するlevel・budgetの分離と、モデル別のトークン数・JSON schema・タイムアウト・1回試行の送信内容を検査した。これも3.5の実サーバー対応を確認したものではない。バージョンを推測で更新せず、requirements.txtの3.0.0を維持する。

## テストと既存データ

基準の200件を削除・無効化せず維持し、新たに26件を追加した。既存Geminiテストの入力・成功／失敗・保存の期待値は維持し、モデルの確認記録だけをテスト専用fixtureで模擬した。モック記録は本番の空の一覧へ残らない。旧2.5が現在利用できるという根拠にはしない。

追加項目：未確認3.5／旧2.5の拒否、モデル未登録時の画面・サーバー側の停止と従来モードへの復帰、モデル別Thinking／トークン数、設定の不正、SDK版違い、確認記録の取り消し、設定変更、5選形式。既存テストで認証・429・タイムアウト・キー／3確認不足・JSON不正・重複・途中失敗時の無保存とPhase 1／Phase 2を検証する。全て一時DBとモックで実施する。

実行結果：Linux・Python 3.12で226件成功、失敗0件、スキップ0件。実Streamlitサーバーで5画面の登録・保存・再起動後の保持も成功。Chromiumで、モデル未確認時の生成無効化、3チェックだけでは送信可能にならないこと、従来モードへ戻って10案を生成できることも確認した。ブラウザ試験では外向き通信とキー読み取りを無効化した。

Windows本人環境での今回の更新全体・実モデルの日本語品質・現在の料金／利用枠は未検証。今回の目的である最新モデルの採用は、公式資料の取得待ちで未完了。

## Windowsでの更新と次の手順

push承認・反映後、アプリを停止しdataをバックアップしてGitHub DesktopでFetch／Pullする。未コミットの変更やsecrets.tomlを上書きしない。依存変更なし。SDK3.0.0が導入済みなら追加セットアップ不要で、既存start_windows.batを使う。

版の確認はAPI通信なしで実行できる。

```powershell
.\.venv\Scripts\python.exe -c "from importlib.metadata import version; print(version('google-genai'))"
.\.venv\Scripts\python.exe -m pip check
```

版違い・未導入なら`.\.venv\Scripts\python.exe -m pip install -r requirements.txt`で揃える。初期化・秘密設定の作り直しは不要。

公式資料を取得できたら、現行の無料モデルと設定を確認して登録し、まずモックで再検証する。実API試験は本人の対象プロジェクトのFree tier／Billing無効・送信内容を確認し、改めて明示承認を得てから1回だけ行う。今回の開発では実API接続、施設自動調査、Canva、TikTok、定期実行を行わない。
