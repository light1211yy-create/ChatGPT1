# Phase 4.3｜Canva無料版・既存テンプレートの自動配置方式調査

調査日：2026-11-09（日本時間）。対象：[Issue #8](https://github.com/light1211yy-create/ChatGPT1/issues/8)。基準main：`4d93e8f769c76e418e9618a560b4b7dafb7db400`。調査ブランチ：`research/phase4-canva-automation`。**本変更はこの文書だけ**で、Issue #7が所有する`studio/canva_package.py`／UI、依存関係、DB、Canvaデザインを変更しない。

## 結論

現時点で最も現実的なのは、[Issue #7](https://github.com/light1211yy-create/ChatGPT1/issues/7)の確認済み7ページ原稿・キャプションと、許諾確認済みの写真を本人が既存Canvaテンプレートの複製へ差し替える方法。無料Canvaを維持し、編集可能なレイアウト・フォント・装飾を残せる。ただし手動工程は残る。

公式REST APIには**既存デザイン複製のpreview定義**がある。さらにAutofillには`create_from_design`と`update_design`の定義があるが、取得した公式仕様では対象プランがPro等であり、今回の無料版運用には採用しない。古い情報を根拠に「複製API自体が存在しない」「AutofillはEnterprise限定」とも断定しない。

Apps SDKには選択画像の置換、選択リッチテキストの編集、現在ページの要素編集の公式例がある。**本人がエディター上で操作する補助アプリ**は将来の調査候補。ただし無料版の利用資格、公開／個人向けアプリの配布条件、7ページ全体の確実な操作、既存テンプレート完全保持は未確認であり、今すぐ無料で安定運用できるとは報告しない。今回はSDKアプリやUI自動操作を実装しない。

## 公式根拠と取得状況

Canvaの開発資料サイト／料金ページは、この開発環境のネットワーク制限でCONNECT 403となった。アカウントへのログイン・APIによる回避は行っていない。一方、Canvaの公式GitHub `canva-sdks`の公開一次資料は取得できた。以下を区別する。

| 資料・公式URL | 今回確認したこと | 状態 |
| --- | --- | --- |
| [Canva Connect API案内](https://www.canva.dev/docs/connect/)／[Apps SDK案内](https://www.canva.dev/docs/apps/) | ページの本文は取得できず。現行の細部・利用資格の直接確認は保留 | 未取得 |
| [Canva料金](https://www.canva.com/pricing/) | 無料版の最新の機能表・利用上限を直接確認できず | 未取得 |
| [公式Connect starter README](https://github.com/canva-sdks/canva-connect-api-starter-kit/blob/fa72bd6e50c447d29d7148ae98dba2f348aa9132/README.md) | Developer Portalでのアプリ／integration登録、Client ID／secret、権限、redirect URL設定が必要。Connect API自身のクライアントSDKは公開せずOpenAPIから生成する案内 | 取得・読取確認済み |
| [公式OpenAPI仕様](https://github.com/canva-sdks/canva-connect-api-starter-kit/blob/fa72bd6e50c447d29d7148ae98dba2f348aa9132/openapi/spec.yml) | 下記のREST機能・資格・preview制約・OAuthを確認 | 取得・読取確認済み |
| [公式Apps starter README](https://github.com/canva-sdks/canva-apps-sdk-starter-kit/blob/814bf4b077028c6ff1dbb095adc6ed74483c3e40/README.md) | Node.js 24／npm 11、TypeScript／React、Developer Portalでの登録、開発URLとCanvaエディター内Previewが必要 | 取得・読取確認済み |
| [Design editing公式例](https://github.com/canva-sdks/canva-apps-sdk-starter-kit/tree/814bf4b077028c6ff1dbb095adc6ed74483c3e40/examples/design_interaction/design_editing) | 要素編集と`session.sync()`、例の`current_page`操作、absoluteページの制限 | README／ソース読取済み、未実行 |
| [Image replacement公式例](https://github.com/canva-sdks/canva-apps-sdk-starter-kit/tree/814bf4b077028c6ff1dbb095adc6ed74483c3e40/examples/content_replacement/image_replacement) | 本人が選択した画像を`upload`→参照置換→`draft.save()`する例 | README／ソース読取済み、未実行 |
| [Rich text replacement公式例](https://github.com/canva-sdks/canva-apps-sdk-starter-kit/tree/814bf4b077028c6ff1dbb095adc6ed74483c3e40/examples/content_replacement/richtext_replacement) | 選択テキストの読み取り、置換、書式変更と保存。例の書式処理は簡略化されているとの注意 | README／ソース読取済み、未実行 |

両リポジトリの取得時HEADは上記の固定コミット。Connectの取得済み`main`のOpenAPI内容と固定コミットの同ファイルが一致することも確認した。仕様の`info.version: 2024-06-18`はAPI仕様の識別子として記録し、資料を2024年の古いスナップショットと推測しない。実際の機能提供・資格・料金はユーザーのアカウントで別途確認する必要がある。SDK例の存在は全Canvaユーザーへの無料提供の証明ではない。

## REST API／Apps SDKで確認できた範囲

### Connect／REST API

公式OpenAPIの該当箇所：

- `POST /v1/designs`／`DesignCreateDesignRequest`：既存designを元に複製する`type: design`、`design_id`、任意の`page_numbers`が定義される。**preview**で、予告なしの破壊的変更があり、preview利用の公開アプリは審査を通過できないとの注意。通常の新規デザイン作成と同一の安定性・資格を仮定しない。複製機能の無料版適用、対象テンプレートの編集性・書式の完全保持は実機未検証。
- `POST /v1/autofills`：`create_from_brand_template`、`create_from_design`、`update_design`。画像／テキスト等のデータフィールドを使う。対象プランの原文は **“Canva Pro (including Canva Education and Canva for Nonprofits), Canva Teams, or Canva Enterprise”**。この一覧は無料版の根拠にならないため採用しない。使用回数制限が今後導入される旨も記載される。
- Autofillは、元デザインに設定したデータフィールドが前提。存在しないフィールド名は黙ってスキップされるため、将来使う場合もdatasetの取得・対応表の検証・不足時停止が必須。通常のテキストボックスを無条件に一括置換できると仮定しない。
- Brand templates APIにも、brand templatesにアクセス可能なプラン（Pro／Teams／Enterprise等）の条件が記載される。無料の既存デザインを勝手にBrand Template扱いしない。
- OAuth Authorization Code＋PKCE、必要scope、redirect URL、トークンの有効期限・更新・取消を管理する必要がある。手動でブラウザにログインした状態をAPI認可として流用しない。Developer Portalの登録や認可・秘密設定の追加は今回行わない。
- 任意の画像を1枚の平面画像として配置する新規design作成は、既存レイアウトのネイティブ要素編集と同じではない。MP4／PNG化・再取り込みも要求された「編集可能な既存テンプレート保持」の代替達成とは報告しない。

これらの詳細は公式ソースが参照する[REST Autofill](https://www.canva.dev/docs/apps/rest-apis/reference/autofills/create-design-autofill-job/)、[Create design](https://www.canva.dev/docs/apps/rest-apis/reference/designs/create-design/)、[認証](https://www.canva.dev/docs/apps/rest-apis/authentication/)、[preview API](https://www.canva.dev/docs/apps/rest-apis/#preview-apis)を次回再確認する。これらのWebページ本文自体は今回取得していない。

### Canva内のApps SDK

- 画像置換例は、ユーザーがエディターで画像要素を選択してから動く。外部Pythonから既存デザイン全体を無人更新する方法の実証ではない。
- Design Editing例は`openDesign({ type: "current_page" })`と編集セッションを使う。サンプルはabsoluteページに制限され、unsupported要素の扱いも必要。対象テンプレートのページ形式、グループ／フレーム／ロック／装飾の対応は実デザインを使わず未検証。
- Rich text例は文字内容と書式の操作が可能だが、例自体が既存の全書式保持を保証しない。フォント、ウェイト、行間、装飾、改行、文字あふれ、上下写真のトリミング等を変更前後で比較する必要がある。
- 公式例は本番用の権限・エラー処理・国際化・アセット配信等が省略された例であり、そのまま実運用へ流用できない。例の画像URLをユーザー写真の代わりに使用しない。
- 登録後の本人エディター内Previewという開発経路は確認できたが、無料アカウントでの資格・個人運用の配布条件・公開アプリ審査・ホスティング等の追加費用は未確認。将来のPoCの前提確認項目として残す。

## 4条件による方式比較

○＝今回の運用方針として満たせる、△＝追加確認・人の確認が必要、×＝現条件では採用不可。○はCanva実機で検証したという意味ではない。

| 方式 | 無料版・追加0円 | 編集可能な既存テンプレート保持 | 写真の権利 | 本人承認 | 判断 |
| --- | --- | --- | --- | --- | --- |
| MAKASE ZIP＋本人が複製・差し替え | ○：現在の無料版操作を継続。Pro素材等は使わない | ○方針：本人が元を複製し、文字／画像だけ変更。実デザインで最終確認 | ○：権利確認後に本人が配置。未確認は空欄 | ○：本人操作・投稿前の確認 | **第一候補**。完全自動ではない |
| Connect／REST Autofill | ×：公式仕様の対象プランに無料版の根拠なし | △：データフィールド付きdesign／templateが必要 | △：別途の検証・アップロード許可が必須 | △：OAuthと対象内容の操作承認を別に設計 | 無料条件を満たさず不採用 |
| RESTによる既存design複製＋別手段で編集 | △：無料資格未確認。複製はpreview | △：複製の定義あり。7ページの編集・書式完全保持は未検証 | △：アップロード時の独立チェックが必要 | △：登録／OAuth／複製操作ごとの承認が必要 | 安定性・無料資格の根拠が不足 |
| Apps SDKで本人が選択した枠へ配置 | △：無料利用・配布・ホスティング条件未確認 | △：選択要素編集例あり。全7ページ／書式は未検証 | △：アセット送信前の権利検証が必要 | ○方針：本人のページ／枠選択→プレビュー→反映 | **次の技術調査候補**。まだ採用・接続しない |
| Windowsの本人立会い操作補助 | △：ツールの利用条件・Canva規約を確認するまで保留 | △：UI変更・座標ずれ・書式変化の危険 | ○方針：許諾確認済み素材だけ操作 | ○方針：1操作／1ページ、停止・取消可能 | SDKが使えない場合の慎重な候補。未実装 |
| PNG／MP4／PDF等に平面化して取り込み | △：形式や機能の利用資格次第 | ×：元の編集可能要素を保持したことにならない | △：元素材の権利は必要 | △：書き出し・取込の承認が必要 | テンプレート保持の代替にしない |

## 写真・情報・承認の設計条件

将来の自動配置では、既存ZIPが保持する権利管理を省略しない。最低限、対象施設との実際の一致、権利者、掲載元、許諾根拠、商用SNS／TikTok用途、Canvaへのアップロード／外部処理、トリミング・文字重ね等の加工、クレジット、期限を確認する。公開サイト／公式サイト／Commonsにあるだけで利用可にしない。許諾の全文や個人情報を外部へ送らず、必要な素材だけを扱う。

原稿確認、写真使用確認、Canvaへの対象素材の送信／配置承認、完成物の確認、外部転送承認を区別する。写真や原稿の版・施設選択・配置対象デザインが変われば以前の承認は流用しない。対象内容をプレビューし、未確認・期限切れ・用途外・対応枠不足なら処理を止める。写真の権利記録をAIで利用可へ変更しない。

元テンプレートは本人が保全し、新しい複製だけを対象にする。配置対応表は次の案で、今回の既存デザインを検査して確定したものではない。

| ページ | 入力 | 変更を許す範囲／確認 |
| --- | --- | --- |
| 1 | 確認済み表紙タイトル／短い本文 | 指定テキストのみ。背景や装飾を変更しない。表紙写真は別途権利確認 |
| 2〜6 | 選択した施設の順に名称／紹介文、各2枚の使用可能写真 | 指定の上下2枠だけ。元の位置・サイズ・フォント等を保持し、トリミングと文字あふれを確認 |
| 7 | 確認済み締めの文 | 指定テキストのみ。投稿先でのキャプション・タグの入力は独立操作 |

元デザインのフレームID・文字の役割・対応ページは未知。名称だけで任意の要素を一括更新せず、将来の明示承認付きテストで対応を確定する。失敗時は自動再実行せず、対象複製を本人が確認してから再開する。

## 次の開発順序・本人に必要となる操作

1. Issue #7のPRとテストを本人が確認し、別途承認のうえ統合する。Issue #8から共有コードへ先に変更しない。
2. 本レポートをレビューし、無料版での本人による複製・差し替えを当面の運用経路とする。Issue #7のZIPは参照URLを持つだけで、画像ファイルを持たない。画像の権利確認・取得・アップロードは本人の別作業。自動取得を今回追加しない。
3. 通信許可後、公式料金・Apps SDKの資格・配布／審査・利用規約・機能サポートを改めて確認する。必要なら本人が無料アカウントのDeveloper Portalの表示を確認するが、登録・認可・秘密情報の取得は別途の明示承認後に限る。確認できなければ手動方式を継続する。
4. 無料条件を満たす根拠が揃った場合にだけ、**別の新規テスト用デザイン**で1枠／1ページのSDK PoCを提案する。本人が許諾済み素材で作ったテスト用複製を指定し、対象内容と変更範囲を承認する。今回の実Canvaデザインを使ったPoCは実施していない。
5. 将来の合格基準：7ページの並び、上下写真2枠、フォント／装飾／配置／改行、文字あふれ、写真と施設の一致、期限・用途・クレジット、変更差分と本人確認を満たす。課金・Proへの変更が要求されたら停止し、アップグレードせず手動に戻す。
6. SDKが使えない場合にだけ、規約確認後の本人立会いWindows操作補助を検討する。無人実行、ログイン情報／Cookieの抽出、CAPTCHA／アクセス制限の回避、非公式API、座標頼りの無確認一括編集は採用しない。ツールの無料性とCanvaの許容範囲も未確認のまま実装しない。

## リスク・未確認・検証の境界

無料資格・料金・規約のWeb本文、実アカウントでのAPI利用、OAuth／SDK登録・審査、実テンプレートのページ形式・要素対応・完全保持、Windows操作補助、実写真の使用権とアップロード可否は未確認。Canvaアカウント／既存デザインへのアクセス・編集、画像取得、有料契約、課金、Gemini／Canva／TikTok実API通信、実キー／秘密設定の読取は行っていない。公式GitHubの静的公開資料の取得と実APIの実行を区別する。

本ブランチは文書1ファイルだけ。main基準の既存テストとQAを実行するが、その成功でCanvaやWindowsの動作・規約・無料利用資格を保証しない。Issue #7のコード／テストは別PRにあり、このブランチへ混ぜない。双方ともmainへの統合は別途承認後に限る。

検証結果：Python 3.12／Linux、`python -m pytest -q tests qa/test_phase12_qa.py`で**347件成功、失敗・エラー・スキップ0件**。この文書以外の差分なし。Canva実アカウント・API・Windowsは未検証。
