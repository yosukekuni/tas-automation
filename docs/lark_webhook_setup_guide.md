# Lark Webhook URL設定ガイド

作成日: 2026-03-15
ステータス: 設計完了・実装待ち

## 概要

GitHub Actions等の自動化スクリプトからLark Botへ通知を送り、
携帯のLarkアプリにプッシュ通知を届ける仕組みの設定手順。

## アーキテクチャ

```
GitHub Actions / ローカルスクリプト
  ↓ HTTP POST (JSON)
Lark Incoming Webhook (Bot)
  ↓
Larkグループチャット
  ↓ プッシュ通知
携帯Larkアプリ
```

## 設定手順

### Step 1: Larkグループチャットの作成（通知専用）

1. Larkアプリで新規グループチャットを作成
2. グループ名: `TAS自動通知` （自分のみのグループでOK）
3. 設定 → ボット → 「カスタムBot」を追加

### Step 2: Incoming Webhook URLの取得

1. カスタムBot追加画面で名前を入力（例: `TAS Bot`）
2. Webhook URLが生成される
3. URL形式: `https://open.larksuite.com/open-apis/bot/v2/hook/xxxxxxxx`
4. このURLをコピー

### Step 3: GitHub Secretsに登録

```bash
cd /path/to/tas-automation
gh secret set LARK_WEBHOOK_URL --body "https://open.larksuite.com/open-apis/bot/v2/hook/xxxxxxxx"
```

### Step 4: ローカル環境にも設定

`/home/user/tokaiair/.env` に追加:
```
LARK_WEBHOOK_URL=https://open.larksuite.com/open-apis/bot/v2/hook/xxxxxxxx
```

## 通知メッセージ仕様

### テキストメッセージ

```python
import requests

def send_lark_notification(webhook_url, title, content):
    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue"
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": content
                }
            ]
        }
    }
    requests.post(webhook_url, json=payload, timeout=10)
```

### テンプレート別カラー

| 用途 | template色 |
|------|-----------|
| 情報 | blue |
| 成功 | green |
| 警告 | orange |
| エラー | red |

## 既存スクリプトでの利用箇所

以下のスクリプトが `LARK_WEBHOOK_URL` 環境変数を参照:
- `task_processor.py` - タスク処理完了通知
- `lark_crm_monitor.py` - CRM変更通知
- `deal_thankyou_email.py` - メール送信通知
- `site_health_audit.py` - サイト異常通知

## 注意事項

- Webhook URLは再生成すると旧URLが無効化される
- 1分あたり100メッセージの制限あり
- Bot追加はグループ管理者権限が必要
- URLは秘密情報として扱い、リポジトリにハードコードしない
