# TOMOSHI（灯し）事業部

## ブランド
- 名称: TOMOSHI / 灯し
- タグライン: 「事業の灯を、消さない。」
- ブランドガイド: /content/tomoshi_brand_guide.md ← **全施策の背骨。ここに立ち返る**
- ドメイン: tomoshi.jp（2026/03/11 ムームードメインで取得済み）
- 商標: 「灯し」は未登録（Toreru 2026/03/11確認）。「TOMOSHI」英字は第11類(照明/Louis Poulsen)のみ。第35類・第36類は空き。

## コンセプト
- 属人的な零細企業を買収 → AI(Claude Code)で業務自動化(1-3ヶ月) → バリュエーション3-5倍
- Phase B: パートナー経由で受託（実績+キャッシュ蓄積）
- Phase C: 自社で企業取得 → AI自動化 → 保有orEXIT
- ターゲット: 町工場, 税理士事務所, 葬儀業, 中古車, 建設, 調剤薬局, 農業
- 競合ゼロ（2026/03時点）。PEファンドの零細版 × AI。

## Infrastructure (2026/03/11構築)

### tomoshi.jp（メインサイト）
- ホスティング: GitHub Pages（無料）
- Repo: https://github.com/yosukekuni/tomoshi-site
- デプロイ: git push → GitHub Actions自動デプロイ
- DNS: ムームードメイン → GitHub Pages (A×4 + CNAME www)
- HTTPS: Let's Encrypt自動（GitHub Pages標準）、Enforce HTTPS有効化済み
- 構造化データ: FAQPage + Service + Organization（index.html内inline JSON-LD）

### WordPress LP（旧・tokaiair.com子ページ）
- Post ID: 5937 → **下書き化+301リダイレクト→tomoshi.jp 設定済み（2026/03/11）**

### メール
- info@tomoshi.jp — Larkエイリアス設定済み（國本アカウントに紐付け）
- MX/SPF/TXT DNS設定完了・認証済み
- **要対応: DKIM未設定**

### SNS
- Facebook: https://www.facebook.com/profile.php?id=61582172220115（Tomoshi名義）
- 初回投稿済み（2026/03/11）

### Lark TOMOSHI CRM（独立Base — TAS CRMとは分離）
- Base Token: UEHQbYevMaFvqIs60r3j92W6puu
- URL: https://ejpe1b5l3u3p.jp.larksuite.com/base/UEHQbYevMaFvqIs60r3j92W6puu

| テーブル | ID |
|---------|-----|
| TOMOSHI_案件 | tblIgzY9xH6vxfSq |
| TOMOSHI_タスク | tblGN8NV9Ox2D1sy |
| TOMOSHI_リード | tblAmZMD8DEWQGw0 |

### Scripts (tas-automation/scripts/)
| Script | Purpose |
|--------|---------|
| tomoshi_lp.py | TOMOSHI LP作成/更新（WP版、旧） |
| tomoshi_schemas.json | 構造化データ(FAQ+Service) |
| ai_valueup_crm_setup.py | CRM 3テーブルセットアップ |
| ai_valueup_nurture.py | メールナーチャリング(5段階: Day 0/3/7/14/21) |
| ai_valueup_lead_monitor.py | リード監視(15分毎) → CEO Lark通知 |
| ai_valueup_table_ids.json | テーブルID保存 |

### GitHub Actions Workflows
| Workflow | Schedule | Purpose |
|----------|----------|---------|
| ai_valueup_monitor.yml | */15 * * * * | リード監視 |
| ai_valueup_nurture.yml | 平日9:00 JST | ナーチャリング送信 |
| deploy.yml (tomoshi-site) | push時 | サイト自動デプロイ |

## 提案先
1. 会社買取センター（タスクールPlus/渡邉智浩）— 名古屋市新事業支援センター加藤TL紹介
2. 事業承継・引継ぎ支援センター（愛知県）
3. 地銀・信金の事業承継部門
4. 三上税理士法人（春日井）— 既存取引先。顧問先の後継者問題へのアプローチ
5. 税理士事務所全般（平均年齢65歳、大量廃業予測）

## コンテンツ
- /content/proposal_kaitori_center.md（会社買取センター向け提案書）
- /content/meeting_script_kaitori_center.md（渡邉氏面談台本）
- /content/tomoshi_brand_guide.md（ブランドガイド）
- tomoshi-site/blog/ — SEO記事6本公開済み:
  1. successor-crisis（後継者がいない会社の5つの選択肢）
  2. black-profit-closure（黒字廃業）
  3. personalization-risk（属人化リスク）
  4. ma-preparation（M&A売却準備）
  5. business-visualization（業務の見える化）
  6. succession-consultation（事業承継の相談先5選）

## 集客施策
- コンテンツSEO: 事業承継関連記事の量産
- SNS: X/LinkedIn で事業承継の課題を定期発信
- 公的機関登録: 事業承継ひろば, BATONZ, 商工会議所
- GBP: TOMOSHI用Googleビジネスプロフィール
- メールシグネチャ: **TOMOSHIとTASは分離する。混ぜない。** TOMOSHI連絡はtomoshi.jpメールから
- 紹介パートナー制度: 税理士・士業向け

## ドメイン注意事項
- tomoshi.jpは中古ドメイン（2016年にsitemap送信履歴あり）
- Search Consoleで手動ペナルティ・被リンクを要確認
- **今後ドメイン取得時は必ずWayback Machine/GSC履歴を事前チェック**

## 戦略メモ
- 融資は実績1社作ってから（ランウェイ1ヶ月では危険）
- 税理士事務所買収 = 顧問先ごと獲得 → 最強のストック収入モデル
- 先行者優位 = カネではなく実績とノウハウの蓄積速度

## tokaiair.com DNS監査結果（2026/03/11）
- 基本設定OK（SSL, リダイレクト, MX, SPF, DMARC）
- **要対応: DKIMレコード未設定**（Lark管理コンソールから値取得→DNS追加）
- **要対応: セキュリティヘッダー全欠落**（HSTS, X-Frame-Options等）
- x-powered-by: PHP/8.3.30 公開中（非表示にすべき）

## スクショ保存先
- `/mnt/c/Users/USER/OneDrive/画像/Screenshots/`（Windowsのスクショはここ）
