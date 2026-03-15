# GA4データ投入設計

作成日: 2026-03-14 / ステータス: 凍結（設計書のみ）

## 概要

GA4/Search Consoleデータを取得し、Web分析Baseの7テーブルに投入するパイプラインを設計する。

## 既存資産の確認

| ファイル | 状態 | 内容 |
|---------|------|------|
| scripts/ga4_analytics.py | 存在確認済み | GA4 & Search Console データ取得、CSV生成 |
| lark_web_analytics_sync.py | 未確認（存在しない可能性） | Lark Baseへの同期 |
| .github/workflows/ga4_analytics.yml | 存在確認済み | 週次実行ワークフロー |

### ga4_analytics.py の現状

- GA4 Property ID: 499408061
- サービスアカウント: service-account@drive-organizer-489313.iam.gserviceaccount.com
- 出力先: /mnt/c/Users/USER/Documents/_data/lark_import/
- CSV形式で出力 → Lark Baseへの自動投入は未実装の可能性

## Web分析Base

- Base Token: Vy65bp8Wia7UkZs8CWCjPSqJpyf
- テーブル構成（7テーブル、要確認）:

| テーブル（推定） | 内容 |
|-----------------|------|
| PV日次 | ページビュー日次データ |
| セッション | セッション数・直帰率・滞在時間 |
| 流入元 | チャネル別流入（Bing/Google/Direct等） |
| キーワード | Search Console検索クエリ |
| ページ別 | ページ別PV・離脱率 |
| コンバージョン | 問い合わせ・電話クリック等 |
| 週次サマリー | 週単位の集計 |

※ 実際のテーブルIDはBase APIで取得して確認が必要

## データ投入フロー

```
GitHub Actions (毎週日曜)
  ↓
ga4_analytics.py
  ├→ GA4 Data API: PV・セッション・流入元・コンバージョン
  ├→ Search Console API: 検索クエリ・表示回数・クリック・順位
  └→ CSV出力
  ↓
lark_web_analytics_sync.py（新規作成）
  ├→ CSV読み込み
  ├→ Web分析Base API (Token: Vy65bp8Wia7UkZs8CWCjPSqJpyf)
  ├→ 7テーブルへ差分投入（日付キーで重複排除）
  └→ 投入結果ログ
```

## 実装方針

### Phase 1: ga4_analytics.py → Lark Base直接投入

- ga4_analytics.pyを拡張し、CSV出力後にLark Base APIで投入
- または別スクリプト lark_web_analytics_sync.py を新規作成

### Phase 2: ダッシュボード連携

- Web分析BaseのダッシュボードビューでKPI表示
- crm_dashboard_design.md のビューと連携

## 工数見積もり

| 作業 | 工数 |
|------|------|
| Web分析Baseテーブル構造確認 | 1時間 |
| lark_web_analytics_sync.py作成 | 4時間 |
| ga4_analytics.yml改修 | 30分 |
| テスト（データ投入確認） | 2時間 |
| **合計** | **7.5時間** |

## 優先順位

**中**: GA4データ自体はga4_analytics.pyで取得済み。Lark Baseへの自動投入で手動CSVインポートを廃止できる。営業KPIの可視化（CRMダッシュボード）と合わせて実装すると効果的。
