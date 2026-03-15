# MCP サーバー統合設計書

作成日: 2026-03-14

## 概要

現在、GA4/GSC・WordPress・Lark の各APIは個別Pythonスクリプトで都度認証コードを書いて呼び出している。これらをMCPサーバー化し、Claude Code から `claude mcp add` で直接接続することで、認証の一元管理とリアルタイム操作を実現する。

### 現状の課題

| 課題 | 影響 |
|------|------|
| 毎スクリプトで認証コード重複 | ga4_analytics.py, lark_crm_monitor.py, wp_safe_deploy.py 等で同一の認証ロジックを繰り返し記述 |
| バッチ実行のみ | GA4データ取得は ga4_analytics.py の定期実行に依存。リアルタイム問い合わせ不可 |
| WordPress操作の断片化 | 記事CRUD・Snippet更新・メディア操作が別スクリプトに分散 |
| Lark API呼び出しの散在 | Base/Drive/Messenger が各スクリプトに埋め込み |

---

## 1. GA4 / Search Console MCP サーバー

### 1.1 Tools 定義

| Tool名 | 説明 | パラメータ |
|---------|------|-----------|
| `ga4_report` | GA4レポート取得（PV・セッション・ユーザー等） | `date_from`, `date_to`, `dimensions[]`, `metrics[]`, `limit`, `order_by` |
| `ga4_realtime` | GA4リアルタイムレポート | `dimensions[]`, `metrics[]` |
| `ga4_top_pages` | PV上位ページ一覧（ショートカット） | `date_from`, `date_to`, `limit` |
| `ga4_traffic_sources` | 流入元分析 | `date_from`, `date_to`, `limit` |
| `gsc_search_analytics` | Search Console検索アナリティクス | `date_from`, `date_to`, `dimensions[]` (query/page/country/device), `row_limit`, `filters[]` |
| `gsc_top_queries` | 検索クエリ上位（ショートカット） | `date_from`, `date_to`, `limit` |
| `gsc_page_performance` | ページ別検索パフォーマンス | `page_url`, `date_from`, `date_to` |
| `gsc_inspect_url` | URL検査（インデックス状態） | `url` |

### 1.2 認証方法

- **方式**: Google Service Account (JWT Bearer)
- **既存資産**: `drive-organizer-489313` サービスアカウント（GA4 readonly + Webmasters readonly スコープ付与済み）
- **キーファイル**: `/mnt/c/Users/USER/Documents/_data/` 配下のサービスアカウントJSON
- **トークン管理**: MCPサーバー内でJWTを生成し、アクセストークンをメモリキャッシュ（有効期限3600秒、期限300秒前に自動リフレッシュ）

```
環境変数:
  GOOGLE_SA_KEY_PATH=/mnt/c/Users/USER/Documents/_data/<sa_key>.json
  GA4_PROPERTY_ID=499408061
  GSC_SITE_URL=sc-domain:tokaiair.com
```

### 1.3 claude mcp add コマンド

```bash
claude mcp add ga4-gsc \
  -e GOOGLE_SA_KEY_PATH=/mnt/c/Users/USER/Documents/_data/<sa_key>.json \
  -e GA4_PROPERTY_ID=499408061 \
  -e GSC_SITE_URL=sc-domain:tokaiair.com \
  -- python3 /mnt/c/Users/USER/Documents/_data/tas-automation/mcp/ga4_gsc_server.py
```

### 1.4 セキュリティ考慮

- サービスアカウントキーは環境変数でパス指定（キー内容を環境変数に入れない）
- スコープは `analytics.readonly` + `webmasters.readonly`（読み取り専用、書き込み権限なし）
- GA4 Property ID をハードコード。他プロパティへのアクセスを防止
- レート制限: GA4 API は 10 req/sec。サーバー側で 0.2秒インターバルを挿入

### 1.5 実装工数

| 項目 | 工数 |
|------|------|
| サーバー骨格（MCP SDK + 認証） | 2時間 |
| GA4 tools (4本) | 2時間 |
| GSC tools (4本) | 2時間 |
| テスト・デバッグ | 1時間 |
| **合計** | **7時間** |

### 1.6 実装構成

```
mcp/
  ga4_gsc_server.py      # MCPサーバー本体
  lib/
    google_auth.py        # SA認証・トークンキャッシュ（ga4_analytics.pyから抽出）
```

---

## 2. WordPress REST API MCP サーバー

### 2.1 Tools 定義

| Tool名 | 説明 | パラメータ |
|---------|------|-----------|
| **記事操作** | | |
| `wp_list_posts` | 記事一覧取得 | `status`, `per_page`, `page`, `search`, `categories[]`, `tags[]`, `order_by` |
| `wp_get_post` | 記事詳細取得 | `post_id` |
| `wp_create_post` | 記事作成 | `title`, `content`, `status`, `categories[]`, `tags[]`, `slug`, `meta{}` |
| `wp_update_post` | 記事更新 | `post_id`, `title`, `content`, `status`, `categories[]`, `tags[]`, `meta{}` |
| `wp_delete_post` | 記事削除 | `post_id`, `force` |
| **ページ操作** | | |
| `wp_list_pages` | 固定ページ一覧 | `status`, `per_page`, `search` |
| `wp_get_page` | 固定ページ詳細 | `page_id` |
| `wp_update_page` | 固定ページ更新（review_agent統合） | `page_id`, `content`, `skip_review` |
| **Code Snippets** | | |
| `wp_list_snippets` | Snippet一覧取得 | `status`, `per_page` |
| `wp_get_snippet` | Snippet詳細取得 | `snippet_id` |
| `wp_update_snippet` | Snippet更新（review_agent統合） | `snippet_id`, `code`, `skip_review` |
| `wp_activate_snippet` | Snippet有効化/無効化 | `snippet_id`, `active` |
| **メディア** | | |
| `wp_list_media` | メディア一覧 | `per_page`, `media_type`, `search` |
| `wp_upload_media` | メディアアップロード | `file_path`, `title`, `alt_text` |
| `wp_delete_media` | メディア削除 | `media_id`, `force` |
| **その他** | | |
| `wp_list_categories` | カテゴリ一覧 | `per_page` |
| `wp_list_tags` | タグ一覧 | `per_page` |
| `wp_get_global_styles` | グローバルスタイル取得 | ― |
| `wp_update_global_styles` | グローバルスタイル更新 | `styles_json` |
| `wp_purge_cache` | LiteSpeed キャッシュパージ要求 | ― |

### 2.2 認証方法

- **方式**: WordPress Application Password (Basic Auth)
- **既存資産**: `automation_config.json` の `wordpress.user` / `wordpress.app_password`
- **エンドポイント**: `https://tokaiair.com/wp-json/wp/v2` (標準) + `https://tokaiair.com/wp-json/code-snippets/v1` (Snippets)

```
環境変数:
  WP_BASE_URL=https://tokaiair.com
  WP_USER=<ユーザー名>
  WP_APP_PASSWORD=<アプリケーションパスワード>
```

### 2.3 claude mcp add コマンド

```bash
claude mcp add wordpress \
  -e WP_BASE_URL=https://tokaiair.com \
  -e WP_USER=$WP_USER \
  -e WP_APP_PASSWORD=$WP_APP_PASSWORD \
  -- python3 /mnt/c/Users/USER/Documents/_data/tas-automation/mcp/wordpress_server.py
```

### 2.4 セキュリティ考慮

- **review_agent 統合**: `wp_update_page` と `wp_update_snippet` は内部で review_agent を呼び出し、CRITICAL判定時は実行拒否（既存 `wp_safe_deploy.py` と同等の安全ガード）
- **CSS禁止ルール**: `inherit!important` パターンを検出したら拒否（ボタン・フッター文字消失の既知バグ）
- **削除操作**: `force=true` を明示しない限りゴミ箱移動のみ
- **WAFリスク**: Code Snippets更新でWAFブロックされる可能性あり。失敗時はエラーメッセージに手動更新手順を含める
- **LiteSpeedキャッシュ**: 変更後は `wp_purge_cache` の実行を推奨するメッセージを返す

### 2.5 実装工数

| 項目 | 工数 |
|------|------|
| サーバー骨格（MCP SDK + Basic Auth） | 1時間 |
| 記事CRUD tools (5本) | 2時間 |
| ページ tools (3本) | 1時間 |
| Code Snippets tools (4本) | 1.5時間 |
| メディア tools (3本) | 1.5時間 |
| その他 tools (5本) | 1時間 |
| review_agent統合 | 1時間 |
| テスト・デバッグ | 2時間 |
| **合計** | **10時間** |

### 2.6 実装構成

```
mcp/
  wordpress_server.py    # MCPサーバー本体
  lib/
    wp_auth.py           # Basic Auth ヘルパー
    review_guard.py      # review_agent連携（wp_safe_deploy.pyから抽出）
```

---

## 3. Lark API MCP サーバー

### 3.1 Tools 定義

| Tool名 | 説明 | パラメータ |
|---------|------|-----------|
| **Base（Bitable）** | | |
| `lark_base_list_records` | テーブルレコード一覧 | `base_token`, `table_id`, `filter`, `sort[]`, `page_size`, `page_token`, `field_names[]` |
| `lark_base_get_record` | レコード取得 | `base_token`, `table_id`, `record_id` |
| `lark_base_create_record` | レコード作成 | `base_token`, `table_id`, `fields{}` |
| `lark_base_update_record` | レコード更新 | `base_token`, `table_id`, `record_id`, `fields{}` |
| `lark_base_batch_update` | レコード一括更新 | `base_token`, `table_id`, `records[]` |
| `lark_base_delete_record` | レコード削除 | `base_token`, `table_id`, `record_id` |
| `lark_base_list_tables` | テーブル一覧取得 | `base_token` |
| `lark_base_search_records` | レコード検索（filter式） | `base_token`, `table_id`, `filter`, `field_names[]`, `page_size` |
| **Drive** | | |
| `lark_drive_list_files` | フォルダ内ファイル一覧 | `folder_token`, `page_size` |
| `lark_drive_get_file_meta` | ファイルメタデータ取得 | `file_token`, `file_type` |
| `lark_drive_upload_file` | ファイルアップロード | `folder_token`, `file_path`, `file_name` |
| `lark_drive_download_file` | ファイルダウンロード | `file_token`, `file_type`, `save_path` |
| `lark_drive_create_folder` | フォルダ作成 | `parent_token`, `name` |
| **Messenger** | | |
| `lark_send_message` | メッセージ送信（DM/グループ） | `receive_id`, `receive_id_type` (open_id/chat_id), `msg_type` (text/interactive/image), `content` |
| `lark_send_card` | インタラクティブカード送信 | `receive_id`, `receive_id_type`, `card_json` |
| `lark_reply_message` | メッセージ返信 | `message_id`, `msg_type`, `content` |
| `lark_webhook_send` | Webhook送信 | `webhook_url`, `msg_type`, `content` |
| **Calendar** | | |
| `lark_calendar_list_events` | イベント一覧 | `calendar_id`, `start_time`, `end_time`, `page_size` |
| `lark_calendar_create_event` | イベント作成 | `calendar_id`, `summary`, `start_time`, `end_time`, `description`, `attendees[]` |
| `lark_calendar_update_event` | イベント更新 | `calendar_id`, `event_id`, `fields{}` |
| `lark_calendar_delete_event` | イベント削除 | `calendar_id`, `event_id` |
| **ユーティリティ** | | |
| `lark_get_user_info` | ユーザー情報取得 | `user_id`, `user_id_type` |
| `lark_get_tenant_token` | テナントトークン取得（デバッグ用） | ― |

### 3.2 認証方法

- **方式**: Lark Internal App (tenant_access_token)
- **既存資産**: App ID `cli_a92d697b1df89e1b` / App Secret（automation_config.json内）
- **トークン管理**: `tenant_access_token` をメモリキャッシュ（有効期限2時間、期限5分前に自動リフレッシュ）
- **エンドポイント**: `https://open.larksuite.com/open-apis/`

```
環境変数:
  LARK_APP_ID=cli_a92d697b1df89e1b
  LARK_APP_SECRET=<app_secret>
  LARK_CRM_BASE_TOKEN=BodWbgw6DaHP8FspBTYjT8qSpOe
  LARK_TASK_BASE_TOKEN=HSSMb3T2jalcuysFCjGjJ76wpKe
  LARK_WEB_ANALYTICS_BASE_TOKEN=Vy65bp8Wia7UkZs8CWCjPSqJpyf
```

### 3.3 claude mcp add コマンド

```bash
claude mcp add lark \
  -e LARK_APP_ID=cli_a92d697b1df89e1b \
  -e LARK_APP_SECRET=$LARK_APP_SECRET \
  -e LARK_CRM_BASE_TOKEN=BodWbgw6DaHP8FspBTYjT8qSpOe \
  -e LARK_TASK_BASE_TOKEN=HSSMb3T2jalcuysFCjGjJ76wpKe \
  -e LARK_WEB_ANALYTICS_BASE_TOKEN=Vy65bp8Wia7UkZs8CWCjPSqJpyf \
  -- python3 /mnt/c/Users/USER/Documents/_data/tas-automation/mcp/lark_server.py
```

### 3.4 セキュリティ考慮

- **スコープ制限**: Lark Admin Consoleで必要最小限の権限のみ付与（bitable:app, drive:drive, im:message, calendar:calendar）
- **Base Token プリセット**: CRM・タスク管理・Web分析の各Base Tokenを環境変数でプリセット。未知のBase Tokenへのアクセスも可能だが、ログに記録
- **メッセージ送信制御**: `lark_send_message` は送信先を制限しない（CEO自身が操作するため）。ただし送信内容・送信先をサーバーログに記録
- **レート制限**: Lark API は 50 req/sec。バッチ操作時は 20 req/sec に自主制限
- **社外秘ルール**: MCP経由で取得したデータの外部出力はClaude Code側の運用ルールで制御（MCPサーバー側では制限しない）

### 3.5 実装工数

| 項目 | 工数 |
|------|------|
| サーバー骨格（MCP SDK + tenant_access_token認証） | 1.5時間 |
| Base tools (8本) | 3時間 |
| Drive tools (5本) | 2時間 |
| Messenger tools (4本) | 1.5時間 |
| Calendar tools (4本) | 1.5時間 |
| ユーティリティ tools (2本) | 0.5時間 |
| テスト・デバッグ | 2時間 |
| **合計** | **12時間** |

### 3.6 実装構成

```
mcp/
  lark_server.py         # MCPサーバー本体
  lib/
    lark_auth.py          # tenant_access_token取得・キャッシュ
    lark_base.py          # Bitable操作ヘルパー（lark_crm_monitor.pyから抽出）
```

---

## 4. 共通設計

### 4.1 ディレクトリ構成

```
tas-automation/
  mcp/
    ga4_gsc_server.py
    wordpress_server.py
    lark_server.py
    lib/
      __init__.py
      google_auth.py
      wp_auth.py
      review_guard.py
      lark_auth.py
      lark_base.py
    requirements.txt
```

### 4.2 技術スタック

- **MCP SDK**: `mcp` Python パッケージ（`pip install mcp`）
- **トランスポート**: stdio（Claude Code 標準）
- **Python**: 3.12+（WSL環境）
- **外部依存**: `mcp`, `cryptography`（Google SA JWT署名用）のみ。urllib標準ライブラリで HTTP 通信

### 4.3 requirements.txt

```
mcp>=1.0.0
cryptography>=42.0.0
```

### 4.4 エラーハンドリング共通方針

| パターン | 対応 |
|----------|------|
| 認証トークン期限切れ | 自動リフレッシュ後リトライ（最大1回） |
| API レート制限 (429) | 指数バックオフ（1s → 2s → 4s、最大3回） |
| ネットワークエラー | エラーメッセージを返す（サーバーは落とさない） |
| 不正なパラメータ | パラメータバリデーションでMCPエラーレスポンスを返す |

### 4.5 ログ

- 全MCPサーバー共通: `stderr` にログ出力（stdout はMCPプロトコル用）
- ログレベル: `INFO`（API呼び出し）、`ERROR`（失敗）、`DEBUG`（環境変数 `MCP_DEBUG=1` で有効）

### 4.6 claude mcp add 一括セットアップ

```bash
#!/bin/bash
# setup_mcp.sh - 3つのMCPサーバーを一括登録

# 1. GA4 / Search Console
claude mcp add ga4-gsc \
  -e GOOGLE_SA_KEY_PATH=/mnt/c/Users/USER/Documents/_data/<sa_key>.json \
  -e GA4_PROPERTY_ID=499408061 \
  -e GSC_SITE_URL=sc-domain:tokaiair.com \
  -- python3 /mnt/c/Users/USER/Documents/_data/tas-automation/mcp/ga4_gsc_server.py

# 2. WordPress
claude mcp add wordpress \
  -e WP_BASE_URL=https://tokaiair.com \
  -e WP_USER=$WP_USER \
  -e WP_APP_PASSWORD=$WP_APP_PASSWORD \
  -- python3 /mnt/c/Users/USER/Documents/_data/tas-automation/mcp/wordpress_server.py

# 3. Lark
claude mcp add lark \
  -e LARK_APP_ID=cli_a92d697b1df89e1b \
  -e LARK_APP_SECRET=$LARK_APP_SECRET \
  -e LARK_CRM_BASE_TOKEN=BodWbgw6DaHP8FspBTYjT8qSpOe \
  -e LARK_TASK_BASE_TOKEN=HSSMb3T2jalcuysFCjGjJ76wpKe \
  -e LARK_WEB_ANALYTICS_BASE_TOKEN=Vy65bp8Wia7UkZs8CWCjPSqJpyf \
  -- python3 /mnt/c/Users/USER/Documents/_data/tas-automation/mcp/lark_server.py
```

---

## 5. 工数サマリー・優先順位

| MCPサーバー | Tools数 | 工数 | 優先度 | 理由 |
|-------------|---------|------|--------|------|
| Lark API | 23 | 12時間 | **P1** | CRM・タスク管理・通知の中核。毎日の操作頻度が最も高い |
| WordPress | 20 | 10時間 | **P2** | 記事更新・Snippet管理が月数回発生。review_agent統合で安全性向上 |
| GA4/GSC | 8 | 7時間 | **P3** | 現状週次バッチで十分機能。リアルタイム化はあると便利レベル |
| **合計** | **51** | **29時間** | | |

### 実装順序の推奨

1. **Phase 1 (Lark)**: CRM操作・タスク管理が最も頻繁。即効性が高い
2. **Phase 2 (WordPress)**: コンテンツ更新の効率化。review_agent統合でデプロイ安全性を維持
3. **Phase 3 (GA4/GSC)**: 週次レポートは既存スクリプトで動作中。余裕があれば実装

---

## 6. 既存スクリプトとの関係

MCPサーバー導入後も、GitHub Actions ワークフローから呼ばれる既存スクリプトはそのまま動作する。MCPサーバーは Claude Code からの対話的操作用であり、既存の自動化パイプラインを置き換えるものではない。

| 既存スクリプト | MCP導入後の扱い |
|---------------|----------------|
| `ga4_analytics.py` | GitHub Actions定期実行は継続。認証ロジックを `lib/google_auth.py` に抽出して共有可能 |
| `lark_crm_monitor.py` | GitHub Actions定期実行は継続。認証ロジックを `lib/lark_auth.py` に抽出して共有可能 |
| `wp_safe_deploy.py` | review_agent統合ロジックを `lib/review_guard.py` に抽出。MCP・CLI両方から利用 |
| `site_health_audit.py` | 変更なし。MCPからのWP読み取りで代替可能だが、専用ロジックが多く移行不要 |
