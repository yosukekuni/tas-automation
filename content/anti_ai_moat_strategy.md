# 競合がClaude Codeを使っても追いつけない堀（Moat）構築戦略

作成日: 2026-03-18
ステータス: 実装中

---

## 前提認識

AIツール（Claude Code含む）で量産できるものは堀にならない:
- SEO記事の量産 → 誰でもできる
- 構造化データの追加 → 技術的に平易
- プログラマティックSEO → テンプレ化済み

**堀になるもの = 自社でしか持てないデータ・シグナル・信頼**

---

## 施策一覧と実装状況

### 施策1: 実データの公開資産化（tokaiair.com）

**概要**: CRM受注台帳の統計データを月次自動更新ページとして公開

**堀のロジック**: 実績データは自社固有。競合がコピーしたらFakeになる。

| 項目 | 状態 |
|------|------|
| スクリプト: `scripts/market_report_generator.py` | 実装済み |
| GitHub Actions: `.github/workflows/market_report.yml` | 実装済み |
| WordPressページ作成（slug: drone-survey-market-report） | **手動作業必要** |
| IndexNow即通知 | スクリプト内組込済み |

**公開データ（社外秘は含まない）**:
- 業種別平均単価（建設/官公庁/不動産/測量コンサル/エネルギー）
- 月別受注トレンド（季節変動の可視化）
- 面積帯別コスト曲線
- 累計案件数・平均単価

**手動作業**:
1. WordPress管理画面で固定ページ作成
   - タイトル: 東海エリア ドローン測量 市場レポート（自社実績ベース）
   - slug: drone-survey-market-report
   - テンプレート: 全幅
2. ページID取得 → `market_report_generator.py` の `MARKET_REPORT_PAGE_ID` に設定
3. 初回実行: `python3 market_report_generator.py --deploy --indexnow`

**月次運用**: GitHub Actionsで毎月1日自動実行

---

### 施策2: ユーザー生成シグナル蓄積ツール

**概要**: ツール利用→PDF DL→リード獲得→利用数を社会的証明として公開

**堀のロジック**: 利用回数・リードデータは蓄積型。後発が「累計3,000件以上」を作るには時間がかかる。

| 項目 | 状態 |
|------|------|
| スクリプト: `scripts/pdf_lead_capture.py` | 実装済み |
| Cloudflare Worker: `cloudflare-worker/pdf-lead-capture-worker.js` | 実装済み（デプロイ前） |
| tokaiair 土量計算ツールのPDF DL機能 | **フロントエンド実装必要** |
| tomoshi 属人化リスク診断のPDF DL機能 | **フロントエンド実装必要** |
| DLカウンター公開表示 | スクリプト内実装済み |

**アーキテクチャ**:
```
ユーザー → 計算ツール → 結果表示
                         ↓
                    「PDF DL」ボタン
                         ↓
                    メール入力モーダル
                         ↓
              Cloudflare Worker (API)
              ├→ KV: DLカウント更新
              ├→ KV: リード一時保存
              └→ PDF生成 & 返却
                         ↓
              pdf_lead_capture.py (cron)
              └→ KV → CRM リード同期
```

**手動作業**:
1. Cloudflare Worker デプロイ（KV Namespace: PDF_LEADS 作成）
2. tokaiair.com 土量計算ページにDLボタン追加
3. tomoshi.jp 診断結果ページにDLボタン追加

---

### 施策3: 被リンク獲得の自動化パイプライン

**概要**: 被リンク獲得先リスト + 申請手順 + メール下書きを自動生成

**堀のロジック**: 被リンクの獲得には「実体のある事業活動」が必須。AIで偽造不可。

| 項目 | 状態 |
|------|------|
| スクリプト: `scripts/backlink_outreach.py` | 実装済み |
| ターゲットリスト（tokaiair 12件 + tomoshi 4件） | 実装済み |
| メール下書きテンプレート | 実装済み |
| 成果物: `content/backlink_outreach/` | 生成コマンド実行で出力 |

**ターゲットカテゴリ**:

tokaiair.com:
- 業界メディア: DRONE.jp, ドローンジャーナル, 建設ITワールド, 日経クロステック
- 公的機関: 名古屋商工会議所, 愛知県産業振興課, J-Net21, i-Construction
- 地域メディア: 名古屋経済新聞, 中部経済新聞
- 比較サイト: ドローン測量比較系, EMEAO!

tomoshi.jp:
- 事業承継ひろば, M&A Online, 中小企業庁ポータル, 名古屋商工会議所

**実行**: `python3 backlink_outreach.py --generate --drafts`

**手動作業**: 生成された下書きを確認・カスタマイズし、メール送信（社外送信はユーザー確認必須）

---

### 施策4: Google口コミ獲得の仕組み化（tokaiair.com）

**概要**: 納品フォローメールに口コミリンクを組み込み、口コミ数を増加

**堀のロジック**: 実顧客からの口コミは偽造できない。数が信頼を作る。

| 項目 | 状態 |
|------|------|
| `post_delivery_followup.py` のURL修正 | 実装済み（暫定URL） |
| GBP PlaceID取得 | **手動作業必要** |
| 口コミ目標設定 | 設計のみ |

**手動作業**:
1. Google Maps で「東海エアサービス株式会社」を検索
2. PlaceIDを取得: https://developers.google.com/maps/documentation/places/web-service/place-id
3. 正しい口コミ直リンクを設定:
   `https://search.google.com/local/writereview?placeid=YOUR_PLACE_ID`
4. `post_delivery_followup.py` の `GOOGLE_REVIEW_URL` を更新

**口コミ目標**:
- 現在: 確認必要
- 3ヶ月目標: 10件以上
- 6ヶ月目標: 20件以上
- 12ヶ月目標: 50件以上

---

### 施策5: ブランド指名検索を増やす施策

**概要**: 全接点でURL統一 + SNS定期発信 + 紙媒体QRコード

**堀のロジック**: 指名検索はSEOで最も強いシグナル。競合がAIで増やすことは不可能。

| 項目 | 状態 |
|------|------|
| スクリプト: `scripts/brand_search_toolkit.py` | 実装済み |
| メール署名テンプレート | 実装済み |
| SNS投稿テンプレート（X/LinkedIn） | 実装済み |
| QRコード設計（名刺・見積書・パンフレット） | 実装済み |
| 成果物: `content/brand_toolkit/` | 生成コマンド実行で出力 |

**実行**: `python3 brand_search_toolkit.py --generate`

**手動作業**:
1. メール署名を全社員に展開
2. 名刺・見積書テンプレートにQRコード追加
3. SNS投稿を週2-3回実施（テンプレート活用）

---

### 施策6: インデックス先行の仕組み化

**概要**: 新ページ公開→IndexNow即通知を全自動化

**堀のロジック**: Googleに「オリジナルソース」として先に認識される。

| 項目 | 状態 |
|------|------|
| tokaiair.com IndexNow | `scripts/indexnow_submit.py` 実装済み |
| WordPress更新→自動IndexNow | GitHub Actions連携済み |
| tomoshi.jp IndexNow | **設計のみ**（GitHub Pages向け） |

**tokaiair.com 現状**:
- IndexNow APIキー設定済み
- `indexnow_submit.py --wordpress --days 1` で直近更新を自動通知可能
- 市場レポートページも公開時に自動通知

**tomoshi.jp 追加設計**:
- GitHub Pages のため、デプロイ後のpost-buildフックでIndexNow送信
- GitHub Actions workflow に IndexNow ステップを追加

```yaml
# tomoshi-site/.github/workflows/deploy.yml に追加
- name: IndexNow notify
  run: |
    curl -X POST "https://api.indexnow.org/indexnow" \
      -H "Content-Type: application/json" \
      -d '{"host":"tomoshi.jp","key":"${{ secrets.INDEXNOW_KEY }}","urlList":["https://tomoshi.jp/"]}'
```

---

### 施策7: 競合監視の自動化

**概要**: 月次で競合サイトの変化を検出し、Lark通知

**堀のロジック**: 直接的な堀ではないが、競合の動きを早期検知して対策。

| 項目 | 状態 |
|------|------|
| スクリプト: `scripts/competitor_monitor.py` | 実装済み |
| GitHub Actions: `.github/workflows/competitor_monitor.yml` | 実装済み |
| Lark Webhook通知 | 実装済み（Webhook URL設定後に有効化） |

**監視対象**:
- tokaiair競合: skymatix.co.jp, terra-drone.net, ipros.jp
- tomoshi競合: （今後追加）
- 自社: tokaiair.com, tomoshi.jp（ベースライン）

**監視項目**:
- sitemapからのページ数増減
- 新規URL検出
- 構造化データ（JSON-LD）の変化
- トップページの変更

---

## 実装済みファイル一覧

### スクリプト
| ファイル | 施策 | 説明 |
|---------|------|------|
| `scripts/market_report_generator.py` | 1 | CRM→市場レポートHTML自動生成 |
| `scripts/pdf_lead_capture.py` | 2 | PDFリード獲得・統計管理 |
| `scripts/backlink_outreach.py` | 3 | 被リンクターゲット・メール下書き生成 |
| `scripts/brand_search_toolkit.py` | 5 | 署名・SNS・QRテンプレート生成 |
| `scripts/competitor_monitor.py` | 7 | 競合サイト月次監視 |

### Cloudflare Worker
| ファイル | 施策 | 説明 |
|---------|------|------|
| `cloudflare-worker/pdf-lead-capture-worker.js` | 2 | PDF DL API（KV連携） |

### GitHub Actions
| ファイル | 施策 | スケジュール |
|---------|------|------|
| `.github/workflows/market_report.yml` | 1 | 毎月1日 9:00 JST |
| `.github/workflows/competitor_monitor.yml` | 7 | 毎月1日 8:00 JST |

### 既存スクリプト修正
| ファイル | 施策 | 変更内容 |
|---------|------|------|
| `scripts/post_delivery_followup.py` | 4 | Google口コミURL修正（PlaceID設定待ち） |

---

## 優先実行順序

### Phase 1: 即実行可能（スクリプト実行のみ）
1. `python3 backlink_outreach.py --generate --drafts` → 被リンクターゲット生成
2. `python3 brand_search_toolkit.py --generate` → ブランドツールキット生成
3. `python3 competitor_monitor.py --check --dry-run` → 競合初回スキャン

### Phase 2: 手動作業込み（1-2日）
4. WordPress固定ページ作成 → market_report_generator.py の初回デプロイ
5. GBP PlaceID取得 → 口コミURL修正
6. メール署名の全社展開

### Phase 3: 開発必要（1-2週間）
7. 土量計算ツールへのPDF DLボタン追加（フロントエンド）
8. Cloudflare Worker デプロイ
9. tomoshi.jp 属人化リスク診断ツール開発
10. tomoshi.jp IndexNow設定

### Phase 4: 継続運用
- 市場レポート月次自動更新
- 競合監視月次チェック
- SNS週2-3回投稿（テンプレート活用）
- 被リンク獲得活動（メール送信は都度ユーザー確認）
- 口コミ数の月次トラッキング

---

## 効果測定KPI

| KPI | 現在 | 3ヶ月後目標 | 6ヶ月後目標 |
|-----|------|------------|------------|
| 「東海エアサービス」指名検索数 | 要計測 | +20% | +50% |
| Google口コミ数 | 要確認 | 10件 | 20件 |
| 被リンクドメイン数 | 要計測 | +5 | +15 |
| 市場レポートPV | 0（未公開） | 100/月 | 300/月 |
| PDFダウンロード数 | 0（未実装） | 50/月 | 200/月 |
| リード獲得数（DL経由） | 0 | 20/月 | 80/月 |

---

## 参考: なぜこれらが「堀」になるのか

| 施策 | AIで複製可能？ | 必要なもの |
|------|---------------|-----------|
| 実績データ公開 | 不可能 | 実際の受注実績 |
| ツール利用数の社会的証明 | 不可能 | 時間の蓄積 |
| 被リンク（公的機関・メディア） | 不可能 | 実体のある事業 |
| Google口コミ | 不可能 | 実顧客の体験 |
| ブランド指名検索 | 不可能 | 認知の蓄積 |
| インデックス先行 | 部分的 | 継続的な先行公開体制 |
| 競合監視 | 可能 | ただし行動が堀を作る |
