# 朝ブリーフィング精査レポート

**実施日**: 2026-03-17
**対象**: scripts/daily_briefing.py + .github/workflows/daily_briefing.yml

---

## 1. 発見した問題と修正

### [BUG修正] GA4セクションが400エラーで失敗
- **原因**: `urllib.parse.urlencode()` が `urn:ietf:params:oauth:grant_type:jwt-bearer` のコロンを二重パーセントエンコードしていた
- **影響**: GA4データが毎朝取得できず「[取得失敗: HTTP Error 400: Bad Request]」と表示
- **修正**: `daily_briefing.py` と `ga4_analytics.py` の両方で、grant_type部分を手動構築に変更
- **修正後確認**: PV: 56 (+17% vs 先週同曜日) 正常取得

### [改善] CRMアラートの可読性向上
- **問題**: 「CRMアラート (137件)」と表示され、全てが同じ緊急度に見えた
- **実態**: Hot/Warm 55件（要対応）+ Cold/不在 82件（大量の古いデータ）
- **改善**: Hot/Warm（要対応）とその他（情報のみ）を分離表示
- **改善後**: 「CRMアラート (要対応: 55件 / 全体: 137件)」

### [新規] Larkカレンダー連携スクリプト作成
- `scripts/lark_calendar_reader.py` を新規作成
- カレンダー権限追加後、daily_briefingに「今日の予定」セクション追加可能
- 権限待ち（ユーザー操作必要）

## 2. 各セクションの品質評価

| # | セクション | 状態 | 評価 |
|---|-----------|------|------|
| 1 | 昨日の商談 | 正常動作 | OK - 更新なし時も正しく表示 |
| 2 | 今日のタスク | 正常動作 | OK - 期限管理タスクを正しく取得 |
| 3 | CRMアラート | 改善済み | OK - Hot/Warm分離で可読性向上 |
| 4 | GA4アクセス | BUG修正 | OK - PV/ユーザー/TOP5ページ正常取得 |
| 5 | 入札情報 | 正常動作 | OK - bid_scanner連携正常 |
| 6 | freee未請求 | 正常動作 | OK - 11件/298万円正しく表示 |
| 7 | freee未入金 | 正常動作 | OK - 20件/892万円、期限超過19件 |

## 3. GitHub Actions ワークフロー確認

- スケジュール: `0 22 * * *` (UTC) = 毎朝7:00 JST -- OK
- Python 3.12 + cryptography -- OK
- secrets: LARK系/GA4/freee全て設定済み -- OK
- /tmp/google_sa.json 書き出し -- OK
- artifact: 14日保存 -- OK

## 4. freee統合の動作確認

freeeセクション（6, 7）は前回追加された機能:
- **未請求**: freee_invoice_creator.py からインポートして未請求案件を検出 -- OK
- **未入金**: freee_payment_checker.py からインポートして未入金/期限超過を検出 -- OK
- 両方とも try/except でfallback（subprocess実行）あり -- 堅牢

## 5. 今後の改善候補

1. **カレンダー連携追加**: 権限付与後に `lark_calendar_reader.py` を daily_briefing に統合
2. **CRM大量Warm対応**: 55件のWarm期限超過は実質的にColdなので、温度感スコアの一括見直しが効果的
3. **freee未入金の古いデータ**: 2023年の期限超過19件は消し込み or 貸倒処理が必要

---

**修正ファイル**:
- `scripts/daily_briefing.py` (GA4 JWT修正 + CRMアラート改善)
- `scripts/ga4_analytics.py` (同じGA4 JWT修正)
- `scripts/lark_calendar_reader.py` (新規作成)
