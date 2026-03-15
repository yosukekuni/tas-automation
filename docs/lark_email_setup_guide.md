# Lark メールアドレス作成 & CRM通知先設定ガイド

最終更新: 2026-03-14

---

## 1. Lark管理コンソールでのメールアドレス作成

### 対象

| 担当者 | メールアドレス | 備考 |
|--------|---------------|------|
| 新美 光 | h.niimi@tokaiair.com | Lark内部ユーザー。DM + メール両方可 |
| 政木 勇治 | _(Larkメール不要)_ | 外部委託。通知は y-masaki@riseasone.jp へメール送信 |

### 前提条件

- tokaiair.com ドメインが Lark に紐付け済みであること
- 管理者権限でログインできること（yosuke.toyoda@gmail.com）

### 手順: 新美 光のメールアドレス作成

1. **管理コンソールにアクセス**
   - https://admin.larksuite.com にアクセスしログイン

2. **メンバー管理を開く**
   - 左メニュー「Organization」>「Members」を選択

3. **新美 光のアカウントを検索**
   - 検索バーで「新美」または open_id `ou_189dc637b61a83b886d356becb3ae18e` で検索
   - 既存アカウントが見つかった場合はそのプロフィールを開く
   - 見つからない場合は「Add Member」で新規作成

4. **メールアドレスの設定**
   - プロフィール編集画面で「Enterprise Email」の項目を確認
   - `h.niimi@tokaiair.com` を入力
   - ※ tokaiair.com ドメインが Lark Mail で有効化されている必要あり

5. **Lark Mail の有効化確認**
   - 左メニュー「Product Settings」>「Email」
   - tokaiair.com ドメインが「Verified」であることを確認
   - ドメイン未設定の場合は「Add Domain」から DNS の MX レコード設定が必要

6. **MXレコード設定（ドメイン未設定の場合のみ）**
   - DNS管理画面で tokaiair.com の MX レコードを Lark のものに変更
   - Lark が提示する MX/SPF/DKIM レコードを設定
   - **注意**: 既存メールサーバーがある場合、切り替えで受信が止まる可能性あり。事前に現在のメール環境を確認すること

7. **動作確認**
   - 新美のアカウントで Lark Mail にログインし、テストメールを送受信

### 政木 勇治について

- **Larkメールアドレスの作成は不要**
- 外部委託のため Lark 内部ユーザーではない（Lark DM 不可）
- CRM通知は既存の `y-masaki@riseasone.jp` へメール送信で対応
- SALES_REPS の `open_id` は `None` のまま維持

---

## 2. CRM監視スクリプトの通知先更新

メールアドレス作成後、以下のスクリプトの SALES_REPS 設定を確認・更新する。

### 影響を受けるファイル一覧

| ファイル | パス | 政木のキー名 |
|---------|------|-------------|
| lark_crm_monitor.py | scripts/lark_crm_monitor.py | `政木`, `ユーザー550372`, `政木 勇治` |
| deal_thankyou_email.py | scripts/deal_thankyou_email.py | `ユーザー550372` |
| delivery_thankyou_email.py | scripts/delivery_thankyou_email.py | `ユーザー550372` |
| post_delivery_followup.py | scripts/post_delivery_followup.py | `ユーザー550372` |
| weekly_sales_report.py | scripts/weekly_sales_report.py | `ユーザー550372` |

### 2-1. lark_crm_monitor.py（L87-93）

現在の設定:
```python
SALES_REPS = {
    "新美光": {"open_id": "ou_189dc637b61a83b886d356becb3ae18e", "email": "h.niimi@tokaiair.com"},
    "新美 光": {"open_id": "ou_189dc637b61a83b886d356becb3ae18e", "email": "h.niimi@tokaiair.com"},
    "政木": {"open_id": None, "email": "y-masaki@riseasone.jp"},
    "ユーザー550372": {"open_id": None, "email": "y-masaki@riseasone.jp"},
    "政木 勇治": {"open_id": None, "email": "y-masaki@riseasone.jp"},
}
```

**既に設定済み。変更不要。**

新美の Lark メールアドレスが有効になった場合、通知経路は:
- `open_id` が設定済み → Lark Bot DM で通知（優先）
- `email` が設定済み → DM失敗時にメールフォールバック

### 2-2. deal_thankyou_email.py / delivery_thankyou_email.py / post_delivery_followup.py（共通構造）

現在の設定:
```python
SALES_REPS = {
    "新美 光": {
        "display": "新美 光",
        "email": "h.niimi@tokaiair.com",
        "open_id": "ou_189dc637b61a83b886d356becb3ae18e",
        "signature": "新美 光\n東海エアサービス株式会社\nTEL: 052-720-5885\nhttps://www.tokaiair.com/",
    },
    "新美光": { ... },  # 同上
    "ユーザー550372": {
        "display": "政木 勇治",
        "email": "y-masaki@riseasone.jp",
        "open_id": None,
        "signature": "政木 勇治\n東海エアサービス株式会社\n...",
    },
}
```

**既に設定済み。変更不要。**

### 2-3. weekly_sales_report.py（L57-70）

現在の設定:
```python
SALES_REPS = {
    "新美 光": {
        "display": "新美",
        "full_name": "新美 光",
        "email": "h.niimi@tokaiair.com",
        "cc_ceo": False,
    },
    "ユーザー550372": {
        "display": "政木",
        "full_name": "政木 勇治",
        "email": "y-masaki@riseasone.jp",
        "cc_ceo": False,
    },
}
```

**既に設定済み。変更不要。**

### 2-4. automation_config.json

現在 `notifications` セクションには Lark Webhook のみ設定:
```json
"notifications": {
    "lark_webhook_url": "${LARK_WEBHOOK_URL}"
}
```

SALES_REPS は各 Python スクリプト内にハードコードされているため、
automation_config.json の変更は **不要**。

将来的に SALES_REPS を一元管理する場合は、automation_config.json に統合し、
各スクリプトからインポートする設計に変更することを推奨。

---

## 3. 政木の通知に関する注意事項

| 項目 | 内容 |
|------|------|
| 契約形態 | 外部委託（業務委託ではなく外部パートナー） |
| Lark DM | 不可（Lark内部ユーザーではない） |
| 通知方法 | メール送信のみ（y-masaki@riseasone.jp） |
| open_id | 全スクリプトで `None` |
| CRMでの表示名 | 「ユーザー550372」（Lark表示名） |
| 通知ロジック | open_id が None → email にフォールバック |

政木への通知が正しく動作するためのチェックポイント:
1. `SALES_REPS` のキーに `ユーザー550372` が含まれていること（CRM上の表示名と一致）
2. `open_id` が `None` であること（DM送信を試みない）
3. `email` が `y-masaki@riseasone.jp` であること

---

## 4. 作業チェックリスト

- [ ] Lark管理コンソールで tokaiair.com ドメインのメール有効化を確認
- [ ] 新美 光のアカウントに h.niimi@tokaiair.com を設定
- [ ] テストメール送受信で動作確認
- [ ] 各スクリプトの SALES_REPS 設定が正しいことを確認（現状は全て設定済み）
- [ ] GitHub Actions の crm_monitor ワークフローでドライラン実行して通知先を確認

---

## 5. 補足: 新美のLark表示名が変更された場合

CRM上の担当営業フィールドの表示名が変わった場合、SALES_REPS のキーを追加する必要がある。
現在は「新美光」「新美 光」の2パターンをカバー済み。
