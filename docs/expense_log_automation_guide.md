# Lark Base Automation: 経費精算ログ自動追加 設定手順書

## 概要

Lark Approval APIのバグにより、経費精算の承認データをAPIで正常に取得できない（instances/listが0件、instances/queryが最新10件のみ返す）。
この問題を回避するため、経費精算が承認されるたびにLark Base Automationを使って「経費精算ログ」テーブルにレコードを自動追加する。

- **対象テーブル**: CRM Base > 経費精算ログ（`tbliYwPFbxxINAfk`）
- **CRM Base ID**: `BodWbgw6DaHP8FspBTYjT8qSpOe`

## 前提条件

- Lark管理者権限があること
- CRM Baseの編集権限があること
- 経費精算（费用报销）の承認フローが設定済みであること
  - approval_code: `25922894-E416-4D50-90E6-EFAF8D88DDC1`

---

## 手順1: Lark Base Automationを開く

1. Lark Baseを開く → CRM Base（`BodWbgw6DaHP8FspBTYjT8qSpOe`）
2. 右上の「自動化（Automation）」ボタンをクリック
3. 「+ ルールを作成」をクリック

## 手順2: トリガーの設定

1. トリガータイプ: **「承認が完了した時」** を選択
   - Lark Base Automationのトリガー一覧から「承認（Approval）」カテゴリを探す
   - 「承認インスタンスのステータスが変更された時」を選択
2. 承認定義の選択:
   - 承認フロー名: **「经费报销」**（費用精算）
   - ※ 日本語表記「経費精算」ではなくLark内部の中国語名で表示される場合あり
3. ステータス条件: **「承認済み（Approved）」** のみ

> **注意**: Lark Base Automationでは承認トリガーが利用できない場合がある。
> その場合は代替手段として以下を検討:
> - **方法A**: Lark Flow（ワークフロー）で承認完了時にWebhookを発火 → Cloudflare Worker経由でBitable APIにレコード追加
> - **方法B**: Lark Base Automationの「定期実行」トリガーで15分おきにApproval APIをポーリング

## 手順3: アクションの設定

1. アクションタイプ: **「レコードを追加」** を選択
2. 対象テーブル: **「経費精算ログ」** を選択
3. フィールドマッピング:

| テーブルフィールド | マッピング元（承認フォーム） | 備考 |
|------------------|--------------------------|------|
| 申請番号 | `serial_id`（シリアル番号） | 202602030001等 |
| 申請者 | `申請者名`（申請人） | |
| 申請日 | `提出日時`（提交时间） | |
| 経費タイプ | `经费类型`（経費タイプ） | 交通費/宿泊費/その他 |
| 理由 | `报销事由`（精算事由） | |
| 内容 | `费用明细.说明`（費用明細の内容） | |
| 日付 | `费用明细.日期`（費用明細の日付） | 経費発生日 |
| 金額 | `费用明细.金额`（費用明細の金額） | 実費（円）|
| 距離km | `距离合计`（距離合計） | メーター距離 |
| ガソリン代 | `距离合计 * 15`（計算式） | 距離x15円。計算式が使えない場合は空欄（payroll_calc.pyで計算） |
| ステータス | 固定値: **「承認済み」** | トリガーが承認済みのみなので固定 |
| 対象月 | `serial_id`の先頭4桁（YYMM） | 計算式で抽出。手動設定の場合は空欄 → 後で手動入力 |
| 備考 | 空欄 | 必要に応じて手動入力 |

## 手順4: テスト

1. ルールを保存して有効化
2. テスト経費精算を1件申請 → 承認
3. 「経費精算ログ」テーブルにレコードが追加されていることを確認
4. 確認項目:
   - 申請番号が正しく入っているか
   - 金額・距離が正しいか
   - 対象月が正しいか（YYMM形式）
   - ステータスが「承認済み」になっているか

## 手順5: 対象月フィールドの補完

Lark Base Automationで対象月の自動設定が難しい場合:
- 申請番号の先頭4桁（例: 202602030001 → 2602）を手動入力
- または、Lark Baseの数式フィールドで `LEFT(申請番号, 4)` を設定

---

## 代替方法: Lark Flow（ワークフロー）経由

Lark Base Automationで承認トリガーが使えない場合:

### A. Lark Flow設定

1. Lark管理コンソール → ワークフロー → 新規作成
2. トリガー: 「承認が完了した時」→ 经费报销 → 承認済み
3. アクション: 「Webhook送信」→ 以下のURLにPOST
   - URL: Cloudflare Worker or GitHub Actions webhook
4. ペイロード: 承認フォームの全フィールド

### B. GitHub Actions Webhook受信

```yaml
# .github/workflows/expense_log_webhook.yml
name: Expense Log Webhook
on:
  repository_dispatch:
    types: [expense_approved]
jobs:
  add_record:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python3 scripts/add_expense_record.py '${{ toJson(github.event.client_payload) }}'
```

---

## payroll_calc.py との連携

`payroll_calc.py` は経費精算ログテーブルからBitable APIで全件取得する:

```python
# 対象月フィルタで該当月のみ取得
TABLE_EXPENSE_LOG = "tbliYwPFbxxINAfk"
# POST /bitable/v1/apps/{base}/tables/{table}/records/search
# filter: 対象月 = "2602" AND ステータス = "承認済み"
```

- Bitable APIは正常動作するため、Approval APIのバグに影響されない
- 対象月フィールドでフィルタするため、全期間のデータを持っていても効率的

## トラブルシューティング

| 症状 | 原因 | 対策 |
|------|------|------|
| レコードが追加されない | トリガーが発火していない | Automation実行ログを確認。承認フロー名が正しいか確認 |
| 対象月が空 | マッピングが設定されていない | 手動で入力するか、数式フィールドに変更 |
| 金額が0 | 費用明細の金額フィールド名が異なる | 承認フォームのフィールド名を確認してマッピング修正 |
| 重複レコード | 同一承認で複数回トリガー | 申請番号で重複チェック（payroll_calc.py側で対応可能） |
