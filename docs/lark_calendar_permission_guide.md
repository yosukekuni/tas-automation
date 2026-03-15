# Lark Calendar API 権限追加手順書

対象アプリ: `cli_a92d697b1df89e1b`
追加権限: `calendar:calendar:readonly` / `calendar:calendar.event:read`

---

## 1. 管理コンソールにログイン

1. ブラウザで https://app.larksuite.com/admin/appCenter/audit にアクセス
2. 管理者アカウントでログイン

## 2. アプリの権限設定画面を開く

1. 左メニュー「Workplace」>「App Management」を選択
2. 「Self-built Apps」タブからアプリ一覧を表示
3. アプリID `cli_a92d697b1df89e1b` のアプリをクリック

> アプリが見つからない場合: https://open.larksuite.com/app/cli_a92d697b1df89e1b に直接アクセスし、Developer Console側から操作する

## 3. Developer Console で権限を追加

管理コンソールではなく Developer Console で権限スコープを追加する必要がある。

1. https://open.larksuite.com/app/cli_a92d697b1df89e1b/permission にアクセス
2. 「Permissions & Scopes」画面が表示される
3. 「+ Add Scopes」ボタンをクリック
4. 検索ボックスに以下を入力し、それぞれチェックを入れる:
   - `calendar:calendar:readonly` — カレンダー情報の読み取り
   - `calendar:calendar.event:read` — カレンダーイベントの読み取り
5. 「Confirm」をクリックして追加

## 4. 権限の承認（Admin Approval）

権限追加後、管理者による承認が必要。

### 方法A: Developer Console から申請

1. 権限追加後、ステータスが「Not activated」と表示される
2. 「Batch activate」または各権限の「Activate」をクリック
3. 管理者承認が求められる場合は、承認リクエストが自動送信される

### 方法B: 管理コンソールで承認

1. https://app.larksuite.com/admin/appCenter/audit にアクセス
2. 「Pending Review」に承認待ちの権限リクエストが表示される
3. 該当アプリの権限リクエストを選択
4. 内容を確認し「Approve」をクリック

### 承認後の確認

- Developer Console の Permissions 画面でステータスが「Activated」になっていること
- 2つとも Activated であること:
  - `calendar:calendar:readonly` — Activated
  - `calendar:calendar.event:read` — Activated

## 5. アプリの再公開（必要な場合）

権限変更後、アプリのバージョンを再公開する必要がある場合がある。

1. Developer Console 左メニュー「Version Management & Release」を開く
2. 「Create Version」をクリック
3. バージョン情報を入力し「Submit for review」
4. 管理者が承認すると新バージョンが公開される

> 既に「自動公開」設定のアプリであれば、この手順は不要

## 6. 動作確認

### API トークン取得

```bash
curl -s -X POST "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal" \
  -H "Content-Type: application/json" \
  -d '{
    "app_id": "cli_a92d697b1df89e1b",
    "app_secret": "<APP_SECRET>"
  }'
```

### カレンダー一覧取得テスト

```bash
curl -s -X GET "https://open.larksuite.com/open-apis/calendar/v4/calendars" \
  -H "Authorization: Bearer <TENANT_ACCESS_TOKEN>" \
  -H "Content-Type: application/json"
```

**成功レスポンス例:**
```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "calendar_list": [...]
  }
}
```

### カレンダーイベント取得テスト

```bash
curl -s -X GET "https://open.larksuite.com/open-apis/calendar/v4/calendars/<CALENDAR_ID>/events" \
  -H "Authorization: Bearer <TENANT_ACCESS_TOKEN>" \
  -H "Content-Type: application/json"
```

**成功レスポンス例:**
```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "items": [...]
  }
}
```

### エラー時の対処

| code | 意味 | 対処 |
|------|------|------|
| 99991664 | 権限不足 | 権限が Activated か確認。再公開が必要な場合あり |
| 99991400 | 無効なトークン | tenant_access_token を再取得 |
| 99991668 | 権限スコープ不足 | 手順3に戻り、必要な権限が追加されているか確認 |

---

作成日: 2026-03-14
