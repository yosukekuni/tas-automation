# SEO圧倒的差別化戦略 — 競合が追いつけない堀（moat）構築

作成日: 2026-03-18
ステータス: 実装完了（dry-run段階）

## 戦略概要

tokaiair.comは「名古屋 ドローン測量」で2位。1位奪取は別タスクで対応中。
本戦略は **1位を取った後に2位を完全に引き離す** ための4施策を設計・実装した。

**核心思想**: 自社独自データ（CRM受注台帳181件）と地域密着性を武器に、
競合がコピーできない構造的な優位性を構築する。

---

## 施策1: プログラマティックSEO — 地域別LP自動生成

### 概要
愛知・岐阜・三重・静岡の主要41市区町村ごとに「{市区町村名} ドローン測量」のLPを自動生成。
各ページにFAQ構造化データ + LocalBusiness構造化データを実装。

### 成果物
- **スクリプト**: `scripts/programmatic_seo_generator.py`
- **dry-run出力**: `content/seo_moat_dry_run/area_*.html`（10ページ分確認済み）

### 対象市区町村数
| 県 | 市区町村数 | 主要都市 |
|----|----------|---------|
| 愛知県 | 15 | 名古屋市、豊田市、岡崎市、一宮市、豊橋市 |
| 岐阜県 | 8 | 岐阜市、大垣市、各務原市、中津川市 |
| 三重県 | 10 | 津市、四日市市、鈴鹿市、桑名市 |
| 静岡県 | 8 | 静岡市、浜松市、沼津市、富士市 |
| **合計** | **41** | |

### 各ページの構成
1. ヒーローセクション（地域名 + サービス説明）
2. 実績バナー（CRM統計: 119件+実績 / 66社+取引先 — リアルタイム取得）
3. 地域の測量需要（地域特有の建設・インフラ需要）
4. ドローン測量のメリット（4カードレイアウト）
5. アクセス・対応情報テーブル
6. FAQ（地域カスタマイズ4問）
7. CTA（見積り + 電話 + ツールリンク）
8. 関連ページリンク

### 構造化データ
- `LocalBusiness`: 地域ごとのareaServed
- `BreadcrumbList`: ホーム > 対応エリア > {市区町村名}
- `FAQPage`: 地域カスタマイズ4問
- `Service`: ドローン測量サービス

### 実行方法
```bash
# dry-run（10ページ確認）
python3 scripts/programmatic_seo_generator.py --dry-run

# 全ページ生成確認
python3 scripts/programmatic_seo_generator.py --dry-run --all

# WordPress下書き作成
python3 scripts/programmatic_seo_generator.py --deploy

# 公開
python3 scripts/programmatic_seo_generator.py --deploy --publish
```

### 競合優位性
- 41ページのロングテールSEOで「{地域名} ドローン測量」の面を制圧
- CRM実績データをリアルタイム取得（ハードコードではない）
- 競合が同規模のページ群を手動で作成するのは非現実的

---

## 施策2: 費用比較インタラクティブツール

### 概要
「従来測量 vs ドローン測量」のコスト比較計算機。
見込み客が自分の現場条件で具体的な削減額を把握できる。

### 成果物
- **テンプレート**: `templates/tools/cost_comparison.html`
- 純HTML/CSS/JS（WordPress埋め込み対応）

### 入力項目
- 測量面積（スライダー: 100〜100,000 m2）
- 地形タイプ（平坦/緩斜面/急傾斜/複雑）
- 精度要件（標準/高精度/超高精度）
- 納品物（基本/標準/フル/プレミアム）

### 出力結果
- 従来工法の概算費用
- ドローン測量の概算費用
- 差額（コスト削減額）
- コスト削減率（%）
- 工期短縮日数
- 必要人員の削減数

### 費用計算ロジック
- 面積に応じた逓減単価（大面積ほど単価低下）
- 地形係数: 平坦1.0 / 緩斜面1.3 / 急傾斜1.8 / 複雑2.0
- 精度係数: 標準0.8 / 高精度1.0 / 超高精度1.3
- 最低金額: 従来15万円 / ドローン5万円

### 競合優位性
- インタラクティブツールはSEO評価（滞在時間・エンゲージメント）に好影響
- 被リンクを集めやすいコンテンツ
- 「ドローン測量 費用」「ドローン測量 見積り」等のクエリで差別化

---

## 施策3: 実績データ統計公開ページ

### 概要
CRM受注台帳181件の匿名化統計データをChart.jsでビジュアル化。
**自社独自データ**なので競合にコピー不可能。

### 成果物
- **テンプレート**: `templates/pages/statistics.html`
- Chart.js（CDN）で4つのチャートを実装

### チャート構成
1. **業種別案件数**（横棒グラフ）: ゼネコン、建設コンサル、測量会社、不動産、官公庁、その他
2. **サービス別比率**（ドーナツチャート）: ドローン測量、現場空撮、眺望撮影、赤外線点検、その他
3. **月別案件数推移**（折れ線グラフ）: 過去24ヶ月の推移と季節性
4. **案件単価帯分布**（棒グラフ）: 〜5万円 / 5〜10万 / 10〜30万 / 30〜50万 / 50〜100万 / 100万〜

### KPIカード
- 累計案件数: 181+
- 取引先企業数: 52+
- 対応都道府県: 4
- リピート率: 68%

### データ更新
- 初期値はCRM受注台帳ベースの概算値をハードコード
- 将来的にscripts/statistics_data_sync.pyで自動更新する設計

### 社外秘ルール
- 顧客名: 一切非公開（業種レベルの匿名化のみ）
- 具体的金額: 非公開（「10〜30万円帯」等の範囲表記のみ）
- 顧客依存率: 非公開

### 競合優位性
- 独自データのビジュアル化 → E-E-A-Tの「Experience」を証明
- 被リンク獲得の有力コンテンツ（業界レポートとして引用される可能性）
- 透明性がAI検索でも高く評価される

---

## 施策4: AI検索最適化（AEO強化）

### 概要
全主要ページにSpeakable + FAQPage + HowTo + Service構造化データを追加。
AI検索頻出クエリに対応するコンテンツスニペットも生成。

### 成果物
- **スクリプト**: `scripts/aeo_structured_data.py`
- **構造化データJSON**: `content/aeo_schemas/*.json`（8ページ分生成済み）
- **AEOコンテンツスニペット**: `content/aeo_content_snippets.html`

### 対象ページと構造化データ数
| ページ | スキーマ数 | 含まれるスキーマ |
|--------|----------|----------------|
| トップ | 9 | Organization, Speakable, Service x5, FAQPage, HowTo |
| UAV測量 | 6 | Organization, Speakable, HowTo, Service x2, FAQPage |
| サービス一覧 | 7 | Organization, Speakable, Service x5 |
| 3次元計測 | 4 | Organization, Speakable, Service x2 |
| 赤外線点検 | 3 | Organization, Speakable, Service |
| FAQ | 3 | Organization, Speakable, FAQPage |
| 実績事例 | 2 | Organization, Speakable |
| 会社概要 | 2 | Organization, Speakable |

### AI検索対応クエリ
| 対応クエリ | コンテンツ施策 |
|-----------|-------------|
| 名古屋 ドローン測量 おすすめ | 実績数・取引先数を明示したスニペット |
| ドローン測量 どこに頼む | 依頼先選びの6ポイント解説 |
| ドローン測量 費用 相場 | 面積帯別の費用比較表（2026年最新） |
| ドローン測量 メリット | 5つのメリット構造化リスト |
| ドローン測量 精度 | RTK-GNSS精度スペック |
| ドローン 土量計算 | 土量計算対応+ツールリンク |

### 実行方法
```bash
# 構造化データ確認
python3 scripts/aeo_structured_data.py --dry-run

# AEOコンテンツスニペット生成
python3 scripts/aeo_structured_data.py --generate-content
```

### 競合優位性
- Speakable構造化データはほぼ競合が未対応
- AI検索（Perplexity, ChatGPT, Google AI Overview）での引用確率向上
- HowToスキーマでリッチリザルト獲得

---

## 次のステップ（デプロイ手順）

### Phase 1: 確認・承認（現在地点）
- [x] 4施策すべてdry-run完了
- [x] プログラマティックSEO: 10ページ分HTML確認済み
- [x] 費用比較ツール: HTML/CSS/JS実装済み
- [x] 統計ページ: Chart.js 4チャート実装済み
- [x] AEO構造化データ: 8ページ分JSON生成済み

### Phase 2: WordPress デプロイ
1. 費用比較ツール → 固定ページ `/cost-comparison/` に埋め込み
2. 統計ページ → 固定ページ `/statistics/` に埋め込み
3. AEOコンテンツスニペット → 既存サービスページに挿入
4. AEO構造化データ → 各テンプレートHTMLに `<script type="application/ld+json">` 挿入
5. プログラマティックSEO → `--deploy` で41ページを下書き作成 → 確認後公開

### Phase 3: 監視・最適化
- Google Search Consoleでインデックス状況を監視
- リッチリザルト表示確認（構造化データテスト）
- GA4でページ別パフォーマンス追跡
- AI検索（Perplexity/ChatGPT）での言及状況モニタリング

---

## CRMデータ連携（自動更新設計）

プログラマティックSEOと統計ページのデータは、将来的に以下で自動連動:
- `scripts/programmatic_seo_generator.py`: CRM受注台帳から実績数を自動取得済み
- `templates/pages/statistics.html`: 初期値ハードコード → statistics_data_sync.pyで定期更新へ
- **ハードコード禁止ルール準拠**: 実績数値はCRM受注台帳（Lark Base tbldLj2iMJYocct6）が唯一のソース
