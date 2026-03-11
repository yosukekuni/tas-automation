# TAS (東海エアサービス) Project Memory

## User: 國本洋輔（旧姓: 豊田洋輔）
- 会社: 東海エアサービス株式会社（ドローン測量会社、名古屋）
- 役割: 経営者・営業支援・クロージング担当（普段は表に出ない）
- Email: yosuke.toyoda@gmail.com
- Lark テナント: ejpe1b5l3u3p.jp.larksuite.com
- 作業スタイル: **全自動で進める。承認画面出さない。本当に大事なことだけ伝える。**
- メール等で「豊田洋輔」「國本洋輔」が混在する
- 目標: 属人性排除・会社スケール・マルチエージェント24/7
- スクショ保存先: /mnt/c/Users/USER/OneDrive/画像/Screenshots/
- **海外移住計画**: 近い将来海外移住予定（場所未定）。会社も海外法人化を検討中。落ち着いたら相談予定。
- **端末**: iPhone 16 Pro。携帯からClaude Code操作したい（Cloudflare Tunnel方式で後日設定予定）
- **NAS**: Synology DS420+, RAID5構成。ScanSnapの格納先。クラウドバックアップ未設定、外部アクセス未設定。

## 営業チーム
- 新美 光: フィールドセールス（229社）
- 政木（ユーザー550372）: フィールドセールス（120社）

## Credentials → automation_config.json
- Lark API: cli_a92d697b1df89e1b (Bot: TAS-Automation, open_id: ou_74cbc6cca06dcd3403d1849a3272b160)
- CRM Base: BodWbgw6DaHP8FspBTYjT8qSpOe
- Web Analytics Base: Vy65bp8Wia7UkZs8CWCjPSqJpyf
- GA4 Property: 499408061
- Google SA: service-account@drive-organizer-489313.iam.gserviceaccount.com
- WordPress: app password設定済み
- Claude API: 設定済み（automation_config.json）
- IndexNow API Key: d6bb8075dd154023876a4281235d93fe

## Lark CRM Base（6テーブル）
| テーブル | ID | 件数 |
|---------|-----|------|
| 取引先 | tblTfGScQIdLTYxA | 531 |
| 連絡先 | tblN53hFIQoo4W8j | 216 |
| 商談 | tbl1rM86nAw9l3bP | 539 |
| 受注台帳 | tbldLj2iMJYocct6 | 185 |
| メールログ | tblfBahatPZMJEM5 | - |
| 支払明細 | tbl0FeQMip23oab3 | 592 |

## タスク管理・会話ログ（独立Base — CRMとは分離）
- Base Token: HSSMb3T2jalcuysFCjGjJ76wpKe
- URL: https://ejpe1b5l3u3p.jp.larksuite.com/base/HSSMb3T2jalcuysFCjGjJ76wpKe

| テーブル | ID | 用途 |
|---------|-----|------|
| タスク管理 | tblGrFhJrAyYYWbV | 全オーダーの進捗管理。毎セッション参照・更新する |
| 会話ログ | tblIyLVn7RFqDbdt | セッション概要・決定事項・作成物・積み残しを記録 |
- **運用ルール**: セッション開始時にタスク管理テーブルを参照。完了時に更新。新オーダーは即追加。

## Lark Forms
- お問い合わせフォーム: 連絡先テーブル view vewJy1Fycy
- 商談報告フォーム: 商談テーブル view vew6ijuGYp (現場に合わせてあるため勝手に変更しない)
- 公開URL: https://ejpe1b5l3u3p.jp.larksuite.com/share/base/form/shrjptotBqSizBmXoyS0bYcYRoe

## 家計管理Base（5テーブル）— 個人用・事業と分離
- Base Token: LcVVbAVrraCAqBsKCbNjjnzapze
- URL: https://ejpe1b5l3u3p.jp.larksuite.com/base/LcVVbAVrraCAqBsKCbNjjnzapze

| テーブル | ID |
|---------|-----|
| 月次収支 | tbluVvYLOONuOZmP |
| 資産残高 | tblJRGyUMSFBmrzF |
| 保険・年金 | tbleYYXYFI24Gevu |
| 教育資金計画 | tblXfvkT1Eh2dsWH |
| ライフイベント | tbljArhUbewDKKTu |

## Web分析Base（7テーブル）— 別Base
- GA4_ページ分析, GSC_検索クエリ, SEO_改善タスク
- GA4_週次トレンド, GA4_流入経路, コンテンツ戦略, 経営インサイト

## 運用方針
- **自発的監査**: 指示を待たず自ら問題を発見→提案→修正。サイト・CRM・スクリプトの定期監査を自主的に行う
- **インシデント駆動自動化**: ミス・クレーム発生→都度相談→チェック/フォーム/通知を即追加。同じミスを2度繰り返さない
- **全体を見る**: 枝葉の最適化に走る前に、構造的な問題（集客母数、ファネル上流）を優先する
- **常時進行**: バックグラウンドで何も動いていない時は、積み残しタスクを自動で進めること。ユーザー操作不要のものから優先的に着手
- **リソース意識**: 大量トークン消費が予想されるオーダー（記事量産、大規模調査等）は事前に申告。可能ならスクリプト化（Claude API直接/GitHub Actions）で対応し、Claude Codeのエージェント多用を避ける
- **外部記憶活用**: タスク管理・会話ログはLark Base（tblGrFhJrAyYYWbV / tblIyLVn7RFqDbdt）に記録。セッション開始時に参照、完了時に更新。「メモリしておいて」指示も即Lark Baseに投入する
- 第1号: 昭和区マンション撮影延長クレーム → 現場作業管理フォーム（tblCdLOHMEE13A5n）+ 終了連絡チェック項目
- フォローメール自動生成: Hot/Warm案件 × 次アクション=メールフォロー → Claude APIでメール生成（auto_followup_email.py）

## Key Scripts（/mnt/c/Users/USER/Documents/_data/）
- `lark_crm_integration.py` — CRM統合
- `lark_api_import.py` — Lark APIインポート
- `ga4_analytics.py` — GA4/GSC取得
- `lark_web_analytics_sync.py` — Web→Lark同期
- `seo_auto_optimizer.py` — WordPress SEO自動更新
- `lark_pl_generator.py` — 月次P&L
- `lark_dashboard_complete.py` — ダッシュボード+OKR
- `lark_crm_monitor.py` — CRM新着監視+携帯通知+品質チェック
- `auto_followup_email.py` — Hot/Warm案件フォローメール自動生成（Claude API）
- `weekly_sales_kpi.py` — 週次営業KPIレポート自動生成
- `auto_quote_generator.py` — 見積自動生成（受注実績ベース単価テーブル）
- `bid_scanner.py` — 入札情報自動スキャン（中部整備局e-bisc）
- `deal_thankyou_email.py` — 商談サンクスメール自動送信（キュー方式）
- `quote_followup.py` — 見積後フォローメール（3/7/14日）
- `lark_command_executor.py` — Lark Botコマンド実行（キーワード+Claude API）
- `automation_config.json` — 全認証情報
- `vps_setup.sh` — VPSセットアップ（CRM監視cron含む）

## GitHub Actions（VPS代替・無料）
- Repo: https://github.com/yosukekuni/tas-automation
- Account: yosukekuni
- Secrets: LARK_APP_ID, LARK_APP_SECRET, CRM_BASE_TOKEN, WEB_ANALYTICS_BASE_TOKEN, GA4_PROPERTY_ID, WP_USER, WP_APP_PASSWORD, ANTHROPIC_API_KEY, LARK_WEBHOOK_URL
- Workflows: crm_monitor(15min), followup_email(平日9時), weekly_kpi(月曜9時), ga4_analytics(日曜9時), bid_scanner(平日8時), keepalive(月1), lark_command(dispatch), quote_followup(平日9時), deal_thankyou(15min+8:30/17:00), case_updater(週次), site_health, lead_nurturing

## コンテンツ戦略
- 土量コスト記事44本 + 買い手向け記事15本公開済み（2026/03/11一括作成、Post ID 5927,5942-5957）
- AEO: 構造化データ、Q&A形式、明確な数値、会社名+地域の反復
- FAQページ30問公開済み（Page ID 4850）
- DXコンサルページ更新済み（Page ID 5931）

## WordPress Tech Notes
- PUT method → 403 (WAF blocks). **Always use POST.**
- Zoho/Google Forms → 全ページLarkフォームに差し替え済み（2026/03/10）
- Yoast SEO installed, sitemap auto-generated
- IndexNow plugin installed (Bing/Google即時通知)
- Google Site Kit installed
- Google Jobs構造化データ: recruit + inside-sales ページに設置済み

## Business Insights
- Bing 68.6%（Google 11.5% = 改善余地大）
- Top: m3-t換算記事 1185PV
- 東海工測依存: 55%
- リピート率: 28%（低い）
- 新規率: 95.9%（リテンション皆無）
- ランウェイ: ~1ヶ月
- 固定費: ¥693,369/月

## CRM Data Quality Issues (2026/03/10)
- 商談ステージ未設定: 224/539 (41.6%)
- 次アクション未設定: 236/539 (43.8%)
- Warm/Hot案件で次アクション未設定: 43件
- 名刺OCRアーティファクト: 13件修正済み（一部姓名逆転の可能性）
- 連絡先: メールなし175/216, 電話なし215/216
- 受注台帳: 空5件削除済み→180件。出典列にステータスあり（受注44/失注29/Gmail67/支払通知63）
- 商談テーブル: 結果・失注理由フィールドは全て未入力

## 給与計算
- 新美光: 業務委託（個人事業主扱い）
- 給与スプレッドシートID: 1dJ2Yx2heeRU9gUnrAv3jrO00zrjxmt6Fo2CaaKnwI_w
- 勤務時間計算DocID: 1qulkz4OLeVeoFPCLBaeXcJ6kBRdQGnvAohflDtp_Hfk
- ※Google SAに共有されていないためAPIアクセス不可（要共有）
- 過去の給与CSV: /mnt/c/Users/USER/Downloads/_organized/data_csv/給与明細：新美光 - 26XX.csv
- 出張申請xlsx: /mnt/c/Users/USER/Downloads/出張申請 YYYYMMDD.xlsx
- 構造: フル日給¥16,000/半日¥8,000/単独撮影¥15,000/点群¥10,560/箇所/複数現場×0.6
- 源泉徴収: 甲欄・扶養1名（配偶者）

## 営業課題（深刻）
- 2人×6ヶ月 = 241商談 → 受注1件（政木: 和合コンサルタント¥450万）
- 新美: 122件中 受注ゼロ。ステージ未設定78件。
- 政木: 119件中 受注1件。ステージ未設定51件。
- ヒアリング→見積検討の変換率 = 0%（両者とも）
- 固定費¥693,369/月×6ヶ月 ≒ ¥416万 vs 受注¥450万 = ほぼトントン
- 和合コンサルタント¥450万受注が受注台帳・CRM商談に未記録
- 商談スクリプト・メールテンプレート作成済み

## 完了タスク
- CRM 6テーブル統合・APIインポート済み
- GA4/GSC連携・分析完了
- SEO自動最適化50件+CTA挿入58件適用済み
- Web分析ダッシュボード（別Base）構築済み
- OKR・KPI25項目・P&L自動生成
- 全設定をautomation_config.jsonに集約
- Zoho/Google Forms → Lark全差し替え完了
- LP全ページmeta description設定完了
- CRM監視スクリプト（lark_crm_monitor.py）作成・初期化済み
- 名刺OCR名前アーティファクト13件修正
- 求人ページZoho→Lark文言置換+Google Jobs構造化データ確認
- IndexNow全更新ページ送信済み
- 受注台帳: 空レコード5件削除、分類完了
- CSS a11y修正（ダークモード対応）全12ページ background:#fff 除去
- Glossary Auto-Link v3（<a>タグネスト防止）— Snippet 34
- 構造化データ（JSON-LD: ProfessionalService, FAQPage, Service）— Snippet 36
- /about/ → /company/ リダイレクト設置
- Navigation修正（/service/ → /services/）
- 壊れたリンク修正（/soil-volume/ 除去）
- tel:リンク設置（contact, footerに050-7117-7141）
- 実績ページ改修: 衛星画像42件, ページネーション(12件+Load More), 注釈追加
- auto_case_updater.py: 受注台帳→実績ページ自動追加スクリプト
- case_updater.yml: GitHub Actions週次ワークフロー
- verify_tasks.py: 31項目自動検証スクリプト
- verification_protocol.md: 検証プロトコルメモリ
- 集客構造計画: /content/acquisition_structure_plan.md（90日アクションプラン）
- LPリデザイン計画: /content/lp_redesign_plan.md

## TOMOSHI事業部 → 詳細: ai_valueup_division.md
- サイト: https://tomoshi.jp/ (GitHub Pages, 10ページ)
- 旧LP: tokaiair.com/services/ai-valueup/ → 301リダイレクト→tomoshi.jp
- メール: info@tomoshi.jp（Larkエイリアス設定済み）
- Facebook: https://www.facebook.com/profile.php?id=61582172220115
- CRM: AI_VU_案件/タスク/リード (3テーブル作成済み)
- 提案先: 会社買取センター, 三上税理士法人(春日井), 事業承継支援センター

## 積み残しタスク
### 自動で進められるもの
- LP全体リデザイン実装（Phase2-3: セグメント別LP、リードマグネット）
- 記事#5-#15の構造化データ追加（WAFブロックのためSnippet経由で要対応）

### ユーザー操作が必要なもの
- DKIM設定（tomoshi.jp + tokaiair.com両方）
- tokaiair.comセキュリティヘッダー（HSTS, X-Frame-Options等）
- tokaiair.com x-powered-by非表示
- Yoast meta descriptionテンプレート設定（WP管理画面）
- 政木のLarkメールアドレス作成
- Lark Webhook URL設定（携帯通知に必要）
- Google SA共有（給与スプレッドシート）
- MAPBOX_TOKEN secret追加（GitHub Actions）

## Cloudflare Worker（Lark Bot）
- Worker URL: https://tas-lark-bot.yosuke-toyoda.workers.dev
- CF API Token: rvPeqCjAREW022u81GGg5_VviAUKcX9OmgGtlwRI
- Lark Verification Token: vjFDBAF7xngfbk1NQoOZfhbo0Xed7ejo
- Encrypt Key: 無効化済み（空）
- キーワードマッチ（無料）: crm/サイトチェック/検証/kpi/入札/ga4/フォロー/品質/実績/サンクス
- Claude APIフォールバック: マッチしないメッセージのみ

## 完了済み（2026/03/11セッション）
- Cloudflare Workers + Lark Bot → GitHub Actions 携帯指示システム ✅テスト完了
- 商談サンクスメール自動送信（キュー方式）: deal_thankyou_email.py + WP Snippet #61
  - 15時前報告→当日17時送信 / 15時後報告→翌営業日8:30送信
  - 送信元: 担当営業個人メール / from: WordPress wp_mail REST API
- 見積送付後フォローメール: quote_followup.py（3/7/14日シーケンス）
- 44記事→ドローン測量CTA内部リンク追加（39記事更新）
- UM/CRP/Zohoプラグイン削除・クリーンアップ
- UMユーザー19名→Lark Base移行
- 記事#1公開: ドローン測量の費用相場 (Post ID 5927)
- GBP最適化プラン作成: /content/gbp_optimization.md
- lark_command_executor.py: キーワードマッチ最適化（API呼び出し90%+削減）
- Phase1 LP: 固定CTAバー(Snippet #56), ヘッダー電話CSS(#58), ページCTAバンド(#59)

## Lark IM Bot
- Bot名: TAS-Automation (open_id: ou_74cbc6cca06dcd3403d1849a3272b160)
- im:message送信: ✅動作確認済み（open_id指定でDM送信可）
- 新美 光: open_id ou_189dc637b61a83b886d356becb3ae18e, user_id 11agc33c, enterprise h.niimi@tokaiair.com
- 國本: open_id ou_d2e2e520a442224ea9d987c6186341ce, user_id eee268c8

## 手動待ちタスク（國本さんの対応が必要）
- **政木のLarkメールアドレス作成**（新美同様にenterprise email付与）
- **Lark Webhook URL設定**（グループチャット→ボット→Webhook追加→URLを共有）← 携帯通知に必須
- **Google SA共有**: 給与スプレッドシート+勤務時間計算を service-account@drive-organizer-489313.iam.gserviceaccount.com に共有
- **NAS外部アクセス設定**: NASモデル・ネットワーク構成の情報を共有してもらう
- **Googleビジネスプロフィール最適化**: ID 5949098016709912880（存在するが未作り込み）
- **Google Ads再開検討**: アカウントあり（過去に運用→効果なくて停止）。必要時にCustomer ID取得
- **SNSアカウント**: 必要であれば運用開始（YouTube/X等）
- **LiteSpeedキャッシュパージ**: CSS/JS変更反映にはWP管理画面からのキャッシュクリアが必要
- **Zoho Campaigns手動削除**: WP管理画面のプラグインページから削除（API削除は500エラー）
- **Ultimate Member → Lark Base移行検討**（中期）: 土量計算アプリのユーザー16名分。UM自体のセキュリティリスクあり
- **GitHub Actions MAPBOX_TOKEN secret追加**: case_updater workflowに必要
- **撮影データ納品 3/13**: パノラマ切り出し＋明度補正
- **MacBook Pro M5 Pro購入**: Calendar reminder 3/13

## 運用ルール
- 矛盾する指示がある場合は國本さんに確認を取る
- 商談報告フォーム（vew6ijuGYp）は勝手に変更しない

## 記事コンテンツ方針
- **実体験・感情・失敗談を入れる**（AI臭さを消す、E-E-A-T対策）
- 過去のやり取りから素材を拾ってOK（社外秘以外）
- **社外秘ライン（絶対に出さない/ぼかす）**:
  - 特定顧客依存率（東海工測55%等）→ NG
  - 営業成績の具体数字（241商談→1件等）→ NG/ぼかす
  - ランウェイ・資金繰り情報 → NG
  - 顧客名・個人名・契約金額 → NG（許可ベース）
- リッチコンテンツ推奨（写真不要）: 比較表、料金テーブル、フロー図、FAQ、数値ハイライト、吹き出し/引用、CTAボックス

## 技術メモ
- Lark Mail API: 読み取り✅。送信はプラン制限で利用不可。IM送信は✅
- Lark Mail: info@tokaiair.com (user_id: eee268c8)。user_mailboxesエンドポイント。body_plain_textはURL-safe base64
- SparkローカルDB: /mnt/c/Users/USER/AppData/Local/Spark Desktop/core-data/databases/messages.sqlite（カラム: messageFromMailbox, receivedDate）
- スクショ: /mnt/c/Users/USER/OneDrive/画像/Screenshots/
- Larkダッシュボード UI作成（APIでは不可）
- VPS契約（Xserver VPS推奨¥830/月）
- 小林さん: kobayashi@st-koo.co.jp ✅ / kobayashi@st-kooco.jp ❌（先方が2つ使うが後者はドメイン不在で常に不達。先方の問題）
- 電話番号: 050-7117-7141
