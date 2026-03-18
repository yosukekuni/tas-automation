# 手作業タスク自動化レポート
**実施日**: 2026-03-18
**実施者**: Claude Agent

---

## 実施結果サマリー

| # | タスク | 判定 | 結果 |
|---|--------|------|------|
| 1 | LiteSpeedパージ | 確認済み | wp_safe_deploy.pyに組込み済み。追加作業なし |
| 2 | Lark Webhook Bot設定 | 手動必要 | API経由でBot作成不可。手順は下記 |
| 3 | Larkカレンダー権限追加 | 手動必要 | 管理コンソールUIのみ。手順は下記 |
| 4 | GBP PlaceID取得 | **自動完了** | ChIJpWtJVIV8A2ARUqf4gLPIFTQ |
| 5 | Google口コミURL修正 | **自動完了** | post_delivery_followup.pyを修正済み |
| 6 | アンケートURL確認 | **自動完了** | /survey/ は404。delivery_thankyou_email.pyからリンク除去済み |
| 7 | KPIダッシュボード | 手動必要 | Lark Base UIのみ |
| 8 | 新美Lark Mailパスワード | 手動必要 | ユーザー確認待ち |
| 9 | GitHub Secrets LOLIPOP_PASSWORD | **自動完了** | gh secret setで登録済み |
| 10 | CRM次アクション営業通知メール | 送信判断待ち | ドラフト作成済み、送信は人間判断 |
| 11 | freee入金消込 | 部分的自動化可 | 調査結果は下記 |
| 12 | Snippet 28 構造化データ | **不要** | AEOスニペット85-91で同等機能デプロイ済み |

**自動化完了: 4件 / 手動必要: 4件 / 不要: 1件 / 判断待ち: 2件 / 部分的: 1件**

---

## 詳細

### 1. LiteSpeedパージ
- **ステータス**: 確認済み
- wp_safe_deploy.py の `_purge_cache()` 関数で、全デプロイ後に自動パージ実行
- LiteSpeedキャッシュパージ用のWPエンドポイント `tas/v1/purge-cache` 経由
- パージ失敗時は警告のみ（デプロイは中断しない）

### 2. Lark Webhook Bot設定
- **ステータス**: 手動必要（5分作業）
- **理由**: LarkのカスタムBot作成はAPI経由では不可。管理UIでのみ作成可能
- **最小手順**:
  1. Larkアプリでグループチャットを開く（または新規作成）
  2. グループ設定 > BOTs > Add Bot > Custom Bot
  3. Bot名「TAS自動通知」、説明「GitHub Actions等の自動通知」
  4. Webhook URLをコピー
  5. `gh secret set LARK_WEBHOOK_URL --body "取得したURL"` を実行
  6. automation_config.json の `notifications.lark_webhook_url` にも同じURLを設定
- **参照**: https://open.larksuite.com/document/ukTMukTMukTM/ucTM5YjL3ETO24yNxkjN

### 3. Larkカレンダー権限追加
- **ステータス**: 手動必要（3分作業）
- **理由**: Lark APIのスコープ追加は開発者コンソールUIのみ
- **最小手順**:
  1. https://open.larksuite.com/app/cli_a92d697b1df89e1b にアクセス
  2. 「Permissions & Scopes」タブを開く
  3. 以下のスコープを検索して追加:
     - `calendar:calendar:readonly`
     - `calendar:calendar.event:read`
  4. 「Apply」をクリック
  5. 管理者承認が必要な場合は承認を実施
- **参照**: https://open.larksuite.com/document/home/introduction-to-scope-and-authorization/permission

### 4. GBP PlaceID取得
- **ステータス**: 自動完了
- **Place ID**: `ChIJpWtJVIV8A2ARUqf4gLPIFTQ`
- **取得方法**: Google Maps Embed API経由でビジネス名「東海エアサービス株式会社」を検索
- **口コミ直リンク**: https://search.google.com/local/writereview?placeid=ChIJpWtJVIV8A2ARUqf4gLPIFTQ

### 5. Google口コミURL修正
- **ステータス**: 自動完了
- **変更ファイル**: `scripts/post_delivery_followup.py`
- **変更内容**:
  - 旧: `https://www.google.com/maps/place/東海エアサービス株式会社/review`（汎用URL、口コミフォームに直接遷移しない）
  - 新: `https://search.google.com/local/writereview?placeid=ChIJpWtJVIV8A2ARUqf4gLPIFTQ`（口コミ投稿フォームに直接遷移）

### 6. アンケートURL /survey/ 実在確認
- **ステータス**: 自動完了
- **確認結果**: `https://www.tokaiair.com/survey/` は404（「何も見つかりませんでした」）
- **変更ファイル**: `scripts/delivery_thankyou_email.py`
- **変更内容**:
  - `SURVEY_URL` を空文字列に変更
  - Claude APIへのプロンプトからアンケートURL誘導セクションを条件付きで除外
  - アンケートページが作成されたら `SURVEY_URL` を再設定するだけで復活可能

### 7. KPIダッシュボードビュー設定
- **ステータス**: 手動必要
- **理由**: Lark Base のダッシュボードビューはAPIで作成不可（UIのみ）
- 手順書は別途作成済み

### 8. 新美Lark Mailパスワード
- **ステータス**: 手動必要
- **理由**: パスワードはユーザー本人から取得する必要あり
- LARK_IMAP_PASSは既にGitHub Secretsに登録済み（2026-03-18T03:25:37Z）
- 追加パスワードが必要な場合はユーザーに確認

### 9. GitHub Secrets LOLIPOP_PASSWORD登録
- **ステータス**: 自動完了
- **実行コマンド**: `gh secret set LOLIPOP_PASSWORD`
- **登録確認**: 2026-03-18T14:35:53Z に登録完了
- automation_config.jsonの `lolipop.password` からGitHub Secretsに同期

### 10. CRM次アクション営業通知メール
- **ステータス**: 送信判断待ち（人間判断）
- ドラフトは作成済み
- 社外向けメール送信はユーザー確認必須（CLAUDE.mdルール）

### 11. freee入金消込
- **ステータス**: 部分的自動化可
- **調査結果**:
  - freee会計APIには「取引の決済（payments）」パラメータがあり、既存取引に対する入金登録が可能
  - `POST /api/1/deals/{deal_id}/payments` で入金を登録できる
  - ただし、銀行口座の入金データ（金額・日付・摘要）の自動取得が必要
  - freeeの銀行API連携で自動取込されている場合は、未処理明細を取得して消込が可能
  - **完全自動化の条件**: freeeの銀行口座連携が有効であること + 消込ルールの設定
- **推奨**: まずfreee上の銀行口座連携状況を確認し、入金データの自動取込ができているかを確認する。できていれば消込自動化スクリプトを開発可能

### 12. Snippet 28 構造化データ
- **ステータス**: 不要（代替済み）
- **理由**: 2026-03-18にAEO構造化データをCode Snippets ID 85-91として全7ページに直接デプロイ済み
- Snippet 28（Yoast Schema Graph統合方式）は不要。wp_head直接出力方式（ID 85-91）のほうが確実に動作する
- 参照: content/deploy_log_20260318.md Step 5

---

## 残タスク（ユーザーアクション必要）

### 優先度高
1. **Lark Webhook Bot設定**（5分）: 上記手順に従いWebhook URLを取得し、GitHub Secretsに登録
2. **Larkカレンダー権限追加**（3分）: 開発者コンソールでスコープ追加

### 優先度中
3. **KPIダッシュボードビュー**（15分）: Lark Base UIで設定
4. **freee入金消込自動化調査**（要確認）: freee銀行口座連携状況の確認

### 優先度低
5. **アンケートページ作成**（任意）: /survey/ に実際のページを作成すれば、メール内のリンクが自動復活
6. **新美Lark Mailパスワード**（確認待ち）: 追加で必要なら連絡
