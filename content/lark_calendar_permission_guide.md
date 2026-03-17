# Larkカレンダー権限追加 手順書

**所要時間**: 約2分
**操作者**: 管理者（國本さん）

---

## 手順

### 1. Lark管理コンソールにアクセス
- URL: https://ejpe1b5l3u3p.jp.larksuite.com/admin/appCenter/audit
- または Lark アプリ > 管理コンソール > アプリ管理

### 2. TAS-Automation Bot を選択
- アプリ一覧から「TAS-Automation」を検索してクリック

### 3. 権限管理を開く
- 左メニューの「権限管理」をクリック

### 4. 以下の権限を追加
検索欄に入力して追加:

| 権限スコープ | 説明 |
|---|---|
| `calendar:calendar:readonly` | カレンダー情報の読み取り |
| `calendar:calendar.event:read` | カレンダーイベントの読み取り |

### 5. 権限を申請・承認
- 「権限を申請」をクリック
- 管理者として自動承認される場合もある

### 6. 動作確認
権限追加後、以下のコマンドで確認:
```bash
python3 scripts/lark_calendar_reader.py
```

---

## 追加後にできること

- daily_briefing.py に「今日の予定」セクションを自動追加
- 面談・打ち合わせの事前準備を自動化
- カレンダーとCRM商談の紐付け

---

**ステータス**: ユーザー操作待ち
