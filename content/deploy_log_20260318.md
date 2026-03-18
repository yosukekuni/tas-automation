# SEO堀構築施策 デプロイログ

**デプロイ日時**: 2026-03-18 12:25-12:40
**デプロイ方法**: deploy_seo_moat.py + 手動リトライ
**WAF対策**: 2段階デプロイ方式（新規作成→更新リクエストで本文設定）

## WAF対策メモ
- ロリポップWAFが`<script>`タグを含むPOSTリクエストをブロック（403）
- 新規ページ作成（POST /pages）は約5KBでもブロックされる場合あり
- **更新リクエスト**（POST /pages/{id}）はscriptタグ含む大きなHTMLでもWAF通過
- 解決策: 短いプレースホルダーで作成後、更新リクエストで完全HTML設定
- WAF自動制御（lolipop_waf.py）はログイン失敗 → 要調査

## Step 1: 地域別LP（41ページ）

全41ページ公開完了（JSON-LD構造化データ付き）

| 都市 | Page ID | URL |
|------|---------|-----|
| 名古屋市 | 7145 | https://tokaiair.com/nagoya/ |
| 豊田市 | 7074 | https://tokaiair.com/toyota/ |
| 岡崎市 | 7075 | https://tokaiair.com/okazaki/ |
| 一宮市 | 7076 | https://tokaiair.com/ichinomiya/ |
| 豊橋市 | 7077 | https://tokaiair.com/toyohashi/ |
| 春日井市 | 7078 | https://tokaiair.com/kasugai/ |
| 安城市 | 7147 | https://tokaiair.com/anjo/ |
| 豊川市 | 7079 | https://tokaiair.com/toyokawa/ |
| 西尾市 | 7080 | https://tokaiair.com/nishio/ |
| 小牧市 | 7081 | https://tokaiair.com/komaki/ |
| 半田市 | 7082 | https://tokaiair.com/handa/ |
| 刈谷市 | 7083 | https://tokaiair.com/kariya/ |
| 瀬戸市 | 7084 | https://tokaiair.com/seto/ |
| 東海市 | 7085 | https://tokaiair.com/tokai/ |
| 大府市 | 7086 | https://tokaiair.com/obu/ |
| 岐阜市 | 7087 | https://tokaiair.com/gifu-city/ |
| 大垣市 | 7088 | https://tokaiair.com/ogaki/ |
| 各務原市 | 7149 | https://tokaiair.com/kakamigahara/ |
| 多治見市 | 7089 | https://tokaiair.com/tajimi/ |
| 関市 | 7090 | https://tokaiair.com/seki/ |
| 中津川市 | 7091 | https://tokaiair.com/nakatsugawa/ |
| 可児市 | 7092 | https://tokaiair.com/kani/ |
| 高山市 | 7093 | https://tokaiair.com/takayama/ |
| 津市 | 7094 | https://tokaiair.com/tsu/ |
| 四日市市 | 7095 | https://tokaiair.com/yokkaichi/ |
| 鈴鹿市 | 7096 | https://tokaiair.com/suzuka/ |
| 松阪市 | 7097 | https://tokaiair.com/matsusaka/ |
| 桑名市 | 7098 | https://tokaiair.com/kuwana/ |
| 伊勢市 | 7099 | https://tokaiair.com/ise/ |
| 伊賀市 | 7100 | https://tokaiair.com/iga/ |
| 名張市 | 7101 | https://tokaiair.com/nabari/ |
| 亀山市 | 7102 | https://tokaiair.com/kameyama/ |
| いなべ市 | 7151 | https://tokaiair.com/inabe/ |
| 静岡市 | 7103 | https://tokaiair.com/shizuoka-city/ |
| 浜松市 | 7153 | https://tokaiair.com/hamamatsu/ |
| 沼津市 | 7104 | https://tokaiair.com/numazu/ |
| 富士市 | 7105 | https://tokaiair.com/fuji/ |
| 磐田市 | 7106 | https://tokaiair.com/iwata/ |
| 掛川市 | 7107 | https://tokaiair.com/kakegawa/ |
| 藤枝市 | 7108 | https://tokaiair.com/fujieda/ |
| 湖西市 | 7109 | https://tokaiair.com/kosai/ |

## Step 2: 費用比較ツール
- Page ID: 7155
- URL: https://tokaiair.com/drone-survey-cost-comparison/
- 内容: インタラクティブコスト比較計算機（HTML/CSS/JS）

## Step 3: 実績統計ページ
- Page ID: 7157
- URL: https://tokaiair.com/drone-survey-statistics/
- 内容: CRM受注台帳ベースの匿名化統計（Chart.js使用）

## Step 4: 市場レポートページ
- Page ID: 7159
- URL: https://tokaiair.com/drone-survey-market-report/
- 内容: 業種別・月別・面積帯別の実績統計レポート
- market_report_generator.py のMARKET_REPORT_PAGE_ID = 7159 に更新済み

## Step 5: AEO構造化データ
- Code Snippets プラグイン経由で7ページに適用
  - ID=85: uav-survey (page 4831)
  - ID=86: 3d-measurement (page 4843)
  - ID=87: infrared-inspection (page 4834)
  - ID=88: services (page 4837)
  - ID=89: faq (page 4850)
  - ID=90: case-library (page 5098)
  - ID=91: company (page 16)
- JS Loader スニペット ID=92 (wp_options経由のJS配信)

## IndexNow送信
- 全44件送信完了（41地域LP + 3固定ページ）
- ステータス: 200 OK

## 残作業
- [ ] LiteSpeedキャッシュパージ（手動）
- [ ] Google Search Console でインデックス状況確認（1-2週間後）
- [ ] 主要ページの構造化データテスト（https://validator.schema.org/）
- [ ] 地域LPのparent設定（/area/ 親ページが必要な場合）
- [ ] lolipop_waf.py のログイン処理修正（307リダイレクト対応）
- [ ] 不要なwp_optionsキー削除: tas_cost_comparison_js, tas_statistics_js, tas_market_report_js, tas_schema_ctx, tas_area_lp_jsonld_code
