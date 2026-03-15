# Lark給与計算システム設定手順書

## 概要

給与計算から明細送信までをLark内で完結させるシステム。
外部API（Approval API）のバグを回避し、Bitable + Bot DMで運用する。

## システム構成

```
経費精算（Lark Approval）
  → 承認時にBase Automation → 経費精算ログテーブル（tbliYwPFbxxINAfk）に自動追加
  → payroll_calc.py が経費精算ログから集計

勤怠（Lark Attendance）
  → payroll_calc.py が Attendance API で自動取得

給与計算テーブル（tbllGwzN1GWwdd4L）
  → payroll_calc.py が計算結果を投入 or 手動入力
  → ステータス「確定」に変更
  → payslip_lark_sender.py で明細カードをBot DM送信
```

## テーブル情報

| テーブル | ID | Base |
|---------|-----|------|
| 給与計算 | tbllGwzN1GWwdd4L | BodWbgw6DaHP8FspBTYjT8qSpOe |
| 経費精算ログ | tbliYwPFbxxINAfk | BodWbgw6DaHP8FspBTYjT8qSpOe |

### 給与計算テーブル フィールド一覧

| フィールド | 型 | 用途 |
|-----------|------|------|
| 対象月 | テキスト | YYMM形式（2602等）|
| 対象者 | テキスト | 新美光 |
| フル出勤日数 | 数値 | |
| 半日出勤日数 | 数値 | |
| 単独撮影日数 | 数値 | |
| 複数現場加算日数 | 数値 | |
| 点群処理箇所数 | 数値 | |
| 基本報酬_現場 | 数値 | フル×16,000+半日×8,000+単独×15,000+複数×9,000 |
| 基本報酬_内業 | 数値 | 点群×10,560 |
| 車両手当 | 数値 | (フル+単独)×1,000+半日×500 |
| ガソリン距離km | 数値 | |
| ガソリン代 | 数値 | 距離×15 |
| 高速代 | 数値 | |
| 駐車場代 | 数値 | |
| 公共交通機関費 | 数値 | |
| その他実費 | 数値 | |
| 経費精算合計 | 数値 | |
| 課税対象額 | 数値 | 現場+内業+車両手当 |
| 源泉徴収税 | 数値 | 甲欄・扶養人数に応じて |
| 総支給額 | 数値 | 課税対象額+経費精算合計 |
| 差引支払額 | 数値 | 総支給額-源泉徴収税 |
| ステータス | 単一選択 | 下書き/確定/送信済み/振込済み |
| 支払日 | 日付 | |
| 備考 | テキスト | |

## Lark Base Automation設定手順

### A. 経費精算 → 経費精算ログテーブル自動追加（設定済み）

既にLark Base Automationで設定済み。
経費精算が承認されると、経費精算ログテーブルにレコードが自動追加される。

### B. 月次経費集計 → 給与計算テーブル反映

Base Automationだけでは月次集計の自動化は困難。以下の方法で運用する。

**方法: payroll_calc.py を月末に実行**

```bash
# 自動計算（API経由で勤怠+経費+撮影実績を取得）
python3 payroll_calc.py --month 2603

# 手動確認後、給与計算テーブルのステータスを「確定」に変更
```

将来的にGitHub Actionsのcronジョブとして月末自動実行も可能。

### C. 給与明細Bot DM送信

**設定手順（Lark管理画面）:**

Lark Base Automationでの自動化は現時点で「ステータス変更→Bot DM送信」のトリガーが
リッチカード送信に対応していないため、スクリプトで代替する。

**運用手順:**

1. 給与計算テーブルで対象月のレコードを確認
2. ステータスを「確定」に変更
3. スクリプトでプレビュー確認:
   ```bash
   python3 payslip_lark_sender.py --month 2602
   ```
   → 國本にプレビューDMが届く

4. 内容確認後、送信:
   ```bash
   python3 payslip_lark_sender.py --month 2602 --send
   ```
   → 対象者にInteractive Cardで給与明細を送信
   → ステータスが自動的に「送信済み」に更新
   → 國本に送信完了通知

## 月次運用フロー

```
月末
  1. 経費精算ログテーブルに当月の承認済み経費が蓄積されていることを確認
  2. payroll_calc.py --month YYMM を実行（勤怠+経費+撮影実績を自動取得）
  3. 給与計算テーブルの計算結果を確認
  4. ステータスを「確定」に変更
  5. payslip_lark_sender.py --month YYMM でプレビュー確認
  6. payslip_lark_sender.py --month YYMM --send で対象者に送信
  7. 振込完了後、ステータスを「振込済み」に変更
```

## スクリプト一覧

| スクリプト | 用途 |
|-----------|------|
| scripts/payroll_calc.py | 勤怠・経費・撮影実績の取得と給与計算 |
| scripts/payslip_lark_sender.py | 給与明細のLark Bot DM送信 |

## 送信先情報

| 対象者 | open_id | 備考 |
|--------|---------|------|
| 新美 光 | ou_189dc637b61a83b886d356becb3ae18e | 業務委託 |
| 國本洋輔 | ou_d2e2e520a442224ea9d987c6186341ce | 確認用 |
