# 日次モーニングレポート設計書

## 概要
毎朝7:00-8:00 JST（22:00-23:00 UTC前日）に自動生成し、Lark Bot DMで國本に配信する日次ダイジェストレポート。

---

## 1. レポート構成

### 1-1. 昨日の商談報告サマリー
- **データソース**: CRM Base 商談テーブル (`tbl1rM86nAw9l3bP`)
- **取得方法**: Lark Bitable API `GET /bitable/v1/apps/{base}/tables/{table}/records`
  - フィルタ: `最終更新日時` が昨日 00:00〜23:59 の商談レコード
  - フィールド: 商談名、担当営業、客先カテゴリ、温度感スコア、ステージ、ヒアリング内容
- **表示内容**:
  - 新規商談数 / 更新商談数
  - 担当営業別の件数
  - ステージ変更があった商談（例: 提案中→見積提出）
  - Hot/Warm案件のハイライト

### 1-2. 今日の予定タスク
- **データソース**: タスク管理Base (`tblGrFhJrAyYYWbV`, Token: `HSSMb3T2jalcuysFCjGjJ76wpKe`)
- **取得方法**: Lark Bitable API
  - フィルタ: `ステータス` != 完了 AND (`期限` = 今日 OR `期限` < 今日)
  - ソート: 期限昇順（期限切れが先頭）
- **表示内容**:
  - 本日期限タスク一覧
  - 期限超過タスク（赤旗表示）
  - 合計件数

### 1-3. CRMアラート要約
- **データソース**: CRM Base 各テーブル（既存 `lark_crm_monitor.py` のロジック再利用）
- **取得方法**: 既存チェック関数を呼び出し
  - 期限超過アクション（`--overdue` 相当）
  - 商談ステージ停滞 14日以上（`--stagnant` 相当）
  - Hot/Warm商談で担当未設定
  - データ品質アラート（`--quality` 相当）
- **表示内容**:
  - アラート種別ごとの件数
  - 上位3件の詳細（全件は省略、CRMリンク付き）

### 1-4. GA4 前日PV
- **データソース**: Google Analytics 4 Data API（Property: `499408061`）
- **取得方法**: `POST analyticsdata.googleapis.com/v1beta/properties/{id}:runReport`
  - dateRanges: 前日1日分
  - metrics: `screenPageViews`, `totalUsers`, `sessions`, `conversions`
  - dimensions: なし（サマリー）+ `pagePath`（TOP5ページ用）
- **認証**: Google Service Account JSON（`GOOGLE_SA_JSON` secret → `/tmp/google_sa.json`）
- **表示内容**:
  - 前日PV / ユーザー数 / セッション数
  - 前週同曜日との比較（%増減）
  - アクセスTOP5ページ
  - CV数（問い合わせフォーム送信）

### 1-5. 入札情報新着
- **データソース**: 既存 `bid_scanner.py` のスキャンロジック再利用
- **取得方法**: `bid_scanner.py` の内部関数を呼び出し（過去1日分）
  - 国交省 中部地方整備局 e-bisc.go.jp
  - 中部地方整備局 cbr.mlit.go.jp
- **表示内容**:
  - 新着入札案件名・公告日・締切日
  - マッチキーワード
  - 該当なしの場合は「新着なし」

---

## 2. レポートフォーマット

```
━━━━━━━━━━━━━━━━━━━━
📊 日次モーニングレポート
{YYYY/MM/DD (曜日)} 07:00
━━━━━━━━━━━━━━━━━━━━

■ 昨日の商談 ({N}件更新)
┌─ 新規: {n}件 / 更新: {m}件
├─ 新美: {x}件 / 政木: {y}件
└─ Hot/Warm: {h}件
  {商談名} → {ステージ変更} ({担当})
  {商談名} → {ステージ変更} ({担当})

■ 今日のタスク ({N}件)
⚠ 期限超過: {n}件
  □ {タスク名} (期限: MM/DD) ← 超過
  □ {タスク名} (期限: 今日)
  □ {タスク名} (期限: 今日)

■ CRMアラート ({N}件)
  🔴 期限超過アクション: {n}件
  🟡 停滞商談(14日+): {m}件
  🟡 データ品質: {q}件
  → {アラート詳細1}
  → {アラート詳細2}

■ GA4 昨日のアクセス
  PV: {N} ({+x%} vs 先週同曜日)
  ユーザー: {N} / セッション: {N}
  CV: {N}件
  TOP: {ページ名} ({PV})
       {ページ名} ({PV})

■ 入札情報 ({N}件)
  📌 {案件名} (締切: MM/DD)
     キーワード: {matched}
  📌 {案件名} (締切: MM/DD)
━━━━━━━━━━━━━━━━━━━━
```

---

## 3. 技術設計

### 3-1. ファイル構成

```
scripts/
  daily_morning_report.py    # メインスクリプト
.github/workflows/
  daily_morning_report.yml   # GitHub Actions定義
```

### 3-2. daily_morning_report.py 構成

```python
#!/usr/bin/env python3
"""日次モーニングレポート - 毎朝7:00 JST自動生成"""

# 依存: 標準ライブラリのみ（urllib, json, datetime）
# 既存モジュール再利用: bid_scanner.py, ga4_analytics.py の関数をimport

def main():
    token = lark_get_token()

    sections = []
    sections.append(build_deal_summary(token))       # 1. 商談サマリー
    sections.append(build_task_overview(token))       # 2. タスク概要
    sections.append(build_crm_alerts(token))          # 3. CRMアラート
    sections.append(build_ga4_summary())              # 4. GA4 PV
    sections.append(build_bid_news())                 # 5. 入札情報

    report = format_report(sections)
    send_lark_dm(token, CEO_OPEN_ID, report)
```

### 3-3. 各セクションのデータ取得

| セクション | API | 認証 | 既存コード再利用 |
|-----------|-----|------|----------------|
| 商談サマリー | Lark Bitable API | LARK_APP_ID/SECRET | `lark_crm_monitor.py` の `lark_get_latest_records()` |
| タスク概要 | Lark Bitable API | LARK_APP_ID/SECRET（タスクBase用Token別途） | 新規実装 |
| CRMアラート | Lark Bitable API | LARK_APP_ID/SECRET | `lark_crm_monitor.py` の各チェック関数 |
| GA4 PV | GA4 Data API v1beta | Google SA JSON | `ga4_analytics.py` の `ga4_page_views()` ベース |
| 入札情報 | 官公庁Webスクレイピング | 不要 | `bid_scanner.py` のスキャン関数 |

### 3-4. 依存シークレット（GitHub Actions）

| Secret名 | 用途 | 既存 |
|----------|------|------|
| `LARK_APP_ID` | Lark API認証 | Yes |
| `LARK_APP_SECRET` | Lark API認証 | Yes |
| `CRM_BASE_TOKEN` | CRM Baseアクセス | Yes |
| `TASK_BASE_TOKEN` | タスク管理Baseアクセス | **新規追加必要**（値: `HSSMb3T2jalcuysFCjGjJ76wpKe`） |
| `GA4_PROPERTY_ID` | GA4プロパティ | Yes |
| `GOOGLE_SA_JSON` | Google SA認証 | Yes |

### 3-5. GitHub Actions Workflow

```yaml
name: Daily Morning Report (7AM JST)

on:
  schedule:
    - cron: '0 22 * * *'  # 22:00 UTC = 07:00 JST
  workflow_dispatch:

jobs:
  report:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Setup config
        env:
          LARK_APP_ID: ${{ secrets.LARK_APP_ID }}
          LARK_APP_SECRET: ${{ secrets.LARK_APP_SECRET }}
          CRM_BASE_TOKEN: ${{ secrets.CRM_BASE_TOKEN }}
          TASK_BASE_TOKEN: ${{ secrets.TASK_BASE_TOKEN }}
          GA4_PROPERTY_ID: ${{ secrets.GA4_PROPERTY_ID }}
          GOOGLE_SA_JSON: ${{ secrets.GOOGLE_SA_JSON }}
        run: |
          python scripts/setup_config.py
          echo "$GOOGLE_SA_JSON" > /tmp/google_sa.json

      - name: Generate and send morning report
        run: python scripts/daily_morning_report.py

      - name: Upload report log
        uses: actions/upload-artifact@v4
        with:
          name: morning-report-${{ github.run_number }}
          path: scripts/morning_report.log
          retention-days: 14
        if: always()
```

### 3-6. setup_config.py 変更

`TASK_BASE_TOKEN` を `config["lark"]` に追加:

```python
"task_base_token": os.environ.get("TASK_BASE_TOKEN", ""),
```

---

## 4. エラーハンドリング

| 障害 | 対応 |
|------|------|
| Lark API障害 | 該当セクション「取得失敗」表示、他セクションは正常送信 |
| GA4 API障害 | 「GA4データ取得失敗」表示、他セクションは正常送信 |
| 官公庁サイト障害 | 「スキャン失敗（サイト応答なし）」表示 |
| 全API障害 | エラーメッセージのみLark DM送信（Lark自体が生きていれば） |
| Lark DM送信失敗 | ログ出力のみ（GitHub Actions artifact確認） |

各セクションは独立したtry/exceptで囲み、1セクションの失敗が全体を止めない設計とする。

---

## 5. 実行時間・コスト見積

| 項目 | 見積 |
|------|------|
| Lark API呼び出し | 5-8回（商談/タスク/各テーブル） |
| GA4 API呼び出し | 2回（サマリー+ページ別） |
| Webスクレイピング | 2-3サイト |
| 総実行時間 | 30-60秒 |
| GitHub Actions消費 | 約1分/日 = 約30分/月（Free枠2000分に余裕あり） |
| 外部API費用 | 全て無料枠内 |

---

## 6. 実装優先度

1. **Phase 1**: 商談サマリー + タスク概要 + Lark DM送信（既存コード流用で即実装可能）
2. **Phase 2**: CRMアラート統合（`lark_crm_monitor.py` から関数切り出し）
3. **Phase 3**: GA4 PV統合（`ga4_analytics.py` から関数切り出し）
4. **Phase 4**: 入札情報統合（`bid_scanner.py` から関数切り出し）

Phase 1-2は既存コードの再利用で1-2時間、Phase 3-4含めて半日で完成見込み。

---

## 7. 前週比較データの保持

GA4前週同曜日比較のため、`morning_report_state.json` に直近7日分のPVデータをキャッシュする。

```json
{
  "daily_pv": {
    "2026-03-13": {"pv": 245, "users": 89, "sessions": 102, "cv": 2},
    "2026-03-12": {"pv": 198, "users": 72, "sessions": 85, "cv": 1}
  }
}
```

---

## 8. 将来拡張

- Lark Interactive Card形式への移行（ボタンでCRM直接遷移）
- 週末は配信スキップ or 簡易版に切替
- Anthropic API連携で「今日の推奨アクション」自動生成
- メールログテーブル連携（昨日の自動送信メール結果サマリー）
