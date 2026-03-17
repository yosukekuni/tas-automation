# Lark Webhook Bot 設定手順書

## 概要

TAS自動化スクリプト群は、Lark Webhookを使ってグループチャットに通知を送信する。
現在 `LARK_WEBHOOK_URL` が未設定のため、Webhook通知は全てスキップされている（エラーにはならない）。

この手順でカスタムBotを作成し、Webhook URLを取得してGitHub Secretsに登録する。

---

## 手順（所要時間: 約2分）

### Step 1: 通知用グループチャットを作成

1. Larkアプリを開く
2. メッセンジャー画面の右上「+」 > 「グループを作成」
3. グループ名: `TAS自動通知` （任意）
4. メンバー: 自分だけでOK（後から追加可能）
5. 「作成」をタップ

### Step 2: カスタムBotを追加

1. 作成したグループチャットを開く
2. グループ名をタップ > 「設定」
3. 「ボット」 > 「ボットを追加」
4. 「カスタムBot」を選択
5. Bot名: `TAS Automation` （任意）
6. 説明: `自動化スクリプト通知` （任意）
7. 「追加」をタップ

### Step 3: Webhook URLをコピー

1. Bot追加完了画面にWebhook URLが表示される
2. `https://open.larksuite.com/open-apis/bot/v2/hook/xxxxxxxx` の形式
3. このURLをコピーする

### Step 4: GitHub Secretsに登録

1. https://github.com/yosukekuni/tas-automation/settings/secrets/actions を開く
2. 「New repository secret」をクリック
3. Name: `LARK_WEBHOOK_URL`
4. Secret: Step 3でコピーしたURL
5. 「Add secret」をクリック

以上で設定完了。次回のワークフロー実行から通知がグループチャットに届く。

---

## 影響範囲

### Webhook通知を使用しているスクリプト（20件）

| スクリプト | 通知内容 | 未設定時の動作 |
|-----------|---------|--------------|
| `lark_crm_monitor.py` | CRM変更検知 | WARNログ出力、処理続行 |
| `weekly_sales_kpi.py` | 週次KPIサマリ | WARNログ出力、処理続行 |
| `auto_followup_email.py` | フォローアップ実行通知 | WARNログ出力、処理続行 |
| `freee_payment_checker.py` | 支払確認結果 | WARNログ出力、処理続行 |
| `freee_invoice_creator.py` | 請求書作成・未登録取引先通知 | WARNログ出力、処理続行 |
| `task_processor.py` | タスク処理結果 | SKIPログ出力、処理続行 |
| `nurture_campaign.py` | ナーチャリング実行通知 | WARNログ出力、処理続行 |
| `email_nurturing_sequences.py` | メールナーチャリング実行通知 | WARNログ出力、処理続行 |
| `seasonal_email.py` | 季節メール送信通知 | WARNログ出力、処理続行 |
| `task_completion_audit.py` | タスク完了監査結果 | stdoutに出力、処理続行 |
| `lib/lark_api.py` | 共通Webhook送信関数 | WARNログ出力、False返却 |

### Webhook未使用（Bot DM直送）のスクリプト

以下はWebhookではなくLark Bot APIでCEOに直接DM送信するため、Webhook設定不要。

| スクリプト | 通知方法 |
|-----------|---------|
| `deal_thankyou_email.py` | Bot DM (open_id) |
| `delivery_thankyou_email.py` | Bot DM (open_id) |
| `post_delivery_followup.py` | Bot DM (open_id) |
| `quote_followup.py` | Bot DM (open_id) |
| `bid_scanner.py` | Bot DM (open_id) |
| `site_health_audit.py` | Bot DM (open_id) |
| `auto_case_updater.py` | Bot DM (open_id) |
| `ai_valueup_lead_monitor.py` | Bot DM (open_id) |
| `ai_valueup_nurture.py` | Bot DM (open_id) |
| `lead_nurturing.py` | Bot DM (open_id) |
| `lark_command_executor.py` | Bot DM (open_id) |
| `daily_briefing.py` | Bot DM (open_id) |
| `payroll_calc.py` | Bot DM (open_id) |
| `wp_safe_deploy.py` | Bot DM (open_id) |

### Fallback動作まとめ

全スクリプトで `LARK_WEBHOOK_URL` 未設定時はWARN/SKIPログを出力して処理を続行する設計。
エラー終了やデータ欠損は発生しない。Webhook設定は通知の利便性向上であり、業務処理自体には影響しない。

---

## GitHub Actions ワークフロー対応状況

以下のワークフローが `secrets.LARK_WEBHOOK_URL` を環境変数として参照済み。
Secretを登録するだけで全ワークフローに反映される。

- crm_monitor.yml
- weekly_kpi.yml
- deal_thankyou.yml
- delivery_thankyou.yml
- post_delivery_followup.yml
- email_nurturing.yml
- weekly_sales_report.yml
- followup_email.yml
- quote_followup.yml
- seasonal_email.yml
- freee_payment_check.yml
- freee_invoice_check.yml
- task_processor.yml
- lark_command.yml
- ai_valueup_monitor.yml
- ai_valueup_nurture.yml
- ga4_analytics.yml
- daily_briefing.yml
- lp_stats_sync.yml

---

## 設定後の確認方法

グループチャットにテスト通知を送信する:

```bash
curl -X POST "YOUR_WEBHOOK_URL" \
  -H "Content-Type: application/json" \
  -d '{"msg_type":"text","content":{"text":"TAS Webhook設定テスト完了"}}'
```

グループチャットに「TAS Webhook設定テスト完了」と表示されればOK。
