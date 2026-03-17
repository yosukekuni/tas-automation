# Lark Bot アラート精査レポート
**作成日**: 2026-03-17
**対象**: tas-automation GitHub Actions 全ワークフロー

---

## 1. アラート送信スクリプト全体像

### 15分間隔（最大ノイズ源）

| スクリプト | ワークフロー | 頻度 | 通知先 | State Cache |
|-----------|-------------|------|--------|-------------|
| lark_crm_monitor.py | crm_monitor.yml | 15分毎 | Webhook + CEO DM + 営業DM | **なし（致命的）** |
| deal_thankyou_email.py --queue | deal_thankyou.yml | 15分毎 | CEO DM | あり |
| delivery_thankyou_email.py --check | delivery_thankyou.yml | 15分毎 | CEO DM | あり |
| ai_valueup_lead_monitor.py | ai_valueup_monitor.yml | 15分毎 | CEO DM | あり |

### 1時間間隔

| スクリプト | ワークフロー | 頻度 | 通知先 | State Cache |
|-----------|-------------|------|--------|-------------|
| task_processor.py | task_processor.yml | 1時間毎 | Webhook | **なし** |

### 日次

| スクリプト | ワークフロー | 頻度 | 通知先 |
|-----------|-------------|------|--------|
| daily_briefing.py | daily_briefing.yml | 毎朝7:00 JST | CEO DM |
| auto_followup_email.py | followup_email.yml | 平日9:00 JST | CEO DM |
| quote_followup.py | quote_followup.yml | 平日9:00 JST | CEO DM |
| email_nurturing_sequences.py | email_nurturing.yml | 平日9:00 JST | CEO DM |
| bid_scanner.py | bid_scanner.yml | 平日8:00 JST | CEO DM |
| freee_payment_checker.py | freee_payment_check.yml | 平日10:00 JST | Webhook |
| freee_invoice_creator.py | freee_invoice_check.yml | 平日9:00 JST | Webhook |
| post_delivery_followup.py | post_delivery_followup.yml | 毎日9:00/10:00 JST | CEO DM |

### 週次

| スクリプト | ワークフロー | 頻度 | 通知先 |
|-----------|-------------|------|--------|
| weekly_sales_kpi.py | weekly_kpi.yml | 月曜9:00 JST | CEO DM |
| weekly_sales_report.py | weekly_sales_report.yml | 月曜/木曜21:00 JST | 営業DM |
| site_health_audit.py | site_health.yml | 日曜7:00 JST | CEO DM |
| lead_nurturing.py | lead_nurturing.yml | 月/水9:00 JST | CEO DM |
| auto_case_updater.py | case_updater.yml | 日曜8:00 JST | CEO DM |
| ga4_analytics.py | ga4_analytics.yml | 日曜9:00 JST | （通知なし、Baseに保存のみ） |

---

## 2. 問題点の特定

### [致命的] CRM Monitor に State Cache がない

**根本原因**: `crm_monitor.yml` に `actions/cache` ステップが一切ない。

GitHub Actionsは毎回クリーンな環境で実行されるため、`crm_monitor_state.json` / `reminder_state.json` / `overdue_state.json` が毎回リセットされる。

**影響**:
- `check_for_new_records()`: 毎回レコード数をINITとして記録するだけ → 新規レコード検出が機能しない（初回と誤認）
- `check_hot_warm_no_action()`: `hot_warm_notified` 日次dedup stateが失われる → **同じHot/Warm未設定案件のアラートが15分毎に繰り返される**
- `check_overdue_actions()`: `overdue_state` が失われる → **同じ期限超過アラートが15分毎に繰り返される**
- `check_new_deal_missing_fields()`: `new_deal_notified` stateが失われる → **同じ入力不足アラートが繰り返される**
- `check_phone_deal_reminder()`: `phone_deal_notified` stateが失われる → **同じリマインドが繰り返される**
- `check_stage_transitions()`: `stage_snapshot` が失われる → 毎回「初回実行」としてスナップショット作成のみ → **受注/失注イベントを永久に検出できない**
- `check_github_actions_health()`: `notified_failure_ids` が失われる → **同じfailure通知が繰り返される**

**ノイズ量の推定**:
- 15分毎 x 24時間 = 96回/日の実行
- Hot/Warm未設定が5件あれば: 5件 x 96回 = **最大480通/日のアラート**（同じ内容）
- 期限超過が3件あれば: 3件 x 96回 = **最大288通/日**
- ステージ変更検知は完全に機能停止

### [重要] deal_thankyou / delivery_thankyou も15分毎にキュー確認通知を送信

- `--queue` モードでCEO DM送信する箇所が複数ある
- 「キュー追加: X件」「対象なし」「既に処理済み」などのステータス通知が15分毎にCEO DMに届く
- 対応不要の「異常なし」通知がノイズ

### [中] task_processor.py もState Cacheなし

- 1時間毎に実行
- 処理タスクがない場合も「対象なし」レポートをWebhookに送信
- ノイズは限定的だが改善余地あり

### [低] 日次スクリプトの「対象なし」通知

- followup_email, quote_followup, lead_nurturing等が対象案件ゼロでもCEO DMに「対象なし」を通知
- 毎日「ゼロ件」通知を受け取っても actionable でない

---

## 3. lark_crm_monitor.py のアラート内訳（15分毎実行の全チェック）

| チェック関数 | 内容 | 通知頻度（設計意図） | 実際の動作（Cacheなし） | 妥当性 |
|-------------|------|---------------------|----------------------|--------|
| check_for_new_records | 新規問い合わせ/商談検出 | 新規時のみ | 毎回INIT（検出不能） | 必要だがCacheないと機能しない |
| check_overdue_actions | Hot/Warm期限超過 | 1日1回/レコード | 15分毎に全件通知 | 本来は有用、頻度問題 |
| check_hot_warm_no_action | Hot/Warm次アクション未設定 | 1日1回/レコード | 15分毎に全件通知 | 本来は有用、頻度問題 |
| check_new_deal_missing_fields | 新規商談ステージ/温度感未入力 | 1日1回/レコード | 15分毎に全件通知 | 本来は有用、頻度問題 |
| check_stage_transitions | 受注/失注ステージ変更 | 変更時のみ | 毎回初回として初期化 | 必要だがCacheないと機能しない |
| check_phone_deal_reminder | 電話後商談報告リマインド | 1日1回/レコード | 15分毎に全件通知 | 必要だが頻度問題 |
| check_action_reminders | 次アクション日リマインド | 朝8時台のみ | 朝8時台のみ（正常） | 適切 |
| check_stagnant_deals | 14日以上停滞 | 朝8時台のみ | 朝8時台のみ（正常） | 適切 |
| check_github_actions_health | GitHub Actions failure | failure時のみ | 同じfailure繰り返し通知 | 必要だがCacheないと機能しない |

---

## 4. 修正内容

### 修正A: crm_monitor.yml に State Cache 追加（最優先）

全stateファイルを `actions/cache` で永続化する。

**対象ファイル**:
- `scripts/crm_monitor_state.json`
- `scripts/reminder_state.json`
- `scripts/overdue_state.json`

### 修正B: lark_crm_monitor.py の通知条件をタイトに

1. `check_overdue_actions()`: Warm案件の即時通知を削除（週次サマリーのみ） → コメントではそう書いてあるが実装が矛盾
2. `check_hot_warm_no_action()`: 同一案件3日連続通知したら週次に格下げ
3. `check_github_actions_health()`: 自動復旧済みの場合は通知スキップ（現在はラベル付けるだけで通知自体はする）

### 修正C: deal_thankyou / delivery_thankyou のステータス通知を抑制

- `--queue` モードで「対象なし」の場合はCEO DM送信をスキップ
- 「キュー追加完了」のみ通知

### 修正D: task_processor.py の「対象なし」Webhook通知を抑制

### 修正E: quote_followup.py の「対象なし」CEO DM通知を抑制

---

## 5. 適用済み修正

### 修正A: crm_monitor.yml に State Cache 追加（最重要）

**ファイル**: `.github/workflows/crm_monitor.yml`

`actions/cache/restore@v5` と `actions/cache/save@v5` を追加。
対象stateファイル:
- `scripts/crm_monitor_state.json` (レコード数、日次dedup、ステージスナップショット)
- `scripts/reminder_state.json` (リマインド送信済みID)
- `scripts/overdue_state.json` (期限超過通知済みID)

これにより全チェック関数の日次dedup・ステージ変更検知が正常に動作する。

### 修正B: check_github_actions_health() で自動復旧済みfailureを通知スキップ

**ファイル**: `scripts/lark_crm_monitor.py` (2187行付近)

`auto_recovered = True` の場合は `send_notification()` をスキップし、ログ出力のみに変更。
一時的なflakeで自動復旧したワークフローのノイズを完全に削除。

### 修正C: check_overdue_actions() でWarm案件の即時通知を削除

**ファイル**: `scripts/lark_crm_monitor.py` (936行付近)

コメントでは「Warmは週次サマリーのみ」と書いてあったが、実装ではWarm案件もHotと同じ即時通知を送信していた矛盾を修正。
Hot案件のみ即時通知、Warm案件はログ出力のみに変更。

### 修正D: task_processor.py の「対象なし」Webhook通知を抑制

**ファイル**: `scripts/task_processor.py` (220行付近)

自動処理対象がゼロの場合にWebhook通知を送っていたのを削除。
1時間毎 x 24時間 = 最大24回/日のノイズを削減。

### 修正E: quote_followup.py の「対象なし」CEO DM通知を抑制

**ファイル**: `scripts/quote_followup.py` (457行, 521行付近)

「見積フォロー: 対象案件なし」「本日送信対象なし」のCEO DM送信を削除。
actionableでない「ゼロ件報告」を排除。

---

## 6. アラート頻度の改善予測

### 修正前（1日あたり推定）
| 送信元 | 推定通知数/日 | 内容 |
|--------|-------------|------|
| CRM Monitor Hot/Warm未設定 | ~96回 | 同じ案件が15分毎 |
| CRM Monitor 期限超過 | ~96回 | 同じ案件が15分毎 |
| CRM Monitor 新規商談入力不足 | ~96回 | 同じ案件が15分毎 |
| CRM Monitor 電話リマインド | ~96回 | 同じ案件が15分毎 |
| CRM Monitor GitHub Actions | ~数回 | 同じfailure繰り返し |
| CRM Monitor ステージ検知 | 0回 | 機能停止 |
| task_processor | ~24回 | 毎時「対象なし」Webhook |
| quote_followup | 1-2回 | 「対象なし」CEO DM |
| **合計** | **~400-500回/日** | |

### 修正後（1日あたり推定）
| 送信元 | 推定通知数/日 | 内容 |
|--------|-------------|------|
| CRM Monitor Hot/Warm未設定 | 1回 | 日次dedup正常動作 |
| CRM Monitor 期限超過 | 1回 | 日次dedup正常動作 |
| CRM Monitor 新規商談入力不足 | 0-2回 | 新規時のみ |
| CRM Monitor 電話リマインド | 0-3回 | 該当時のみ |
| CRM Monitor GitHub Actions | 0-1回 | 実際のfailure時のみ |
| CRM Monitor ステージ検知 | 0-2回 | 受注/失注時のみ（正常動作） |
| deal_thankyou | 0-3回 | キュー追加時のみ |
| delivery_thankyou | 0-2回 | キュー追加時のみ |
| **合計** | **5-15回/日** | **98%削減** |
