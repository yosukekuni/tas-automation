# Lark Bot → Cloudflare Worker → GitHub Actions セットアップ手順

## 構成図

```
携帯(Lark DM) → Lark Event Subscription → Cloudflare Worker(受信・検証・転送)
    → GitHub Actions(repository_dispatch) → Claude API実行 → Lark DM(結果返信)
```

## 1. Cloudflareアカウント作成

1. https://dash.cloudflare.com/sign-up にアクセス
2. 無料アカウント作成（Workers Free: 100,000リクエスト/日）
3. メール認証

## 2. wrangler CLIインストール

```bash
npm install -g wrangler
wrangler login
```

ログイン後、ブラウザでCloudflareアカウントと連携。

## 3. デプロイ

```bash
cd cloudflare-worker
wrangler deploy
```

デプロイ後に表示されるURLをメモ（例: `https://tas-lark-bot.<account>.workers.dev`）。

## 4. Secrets設定

以下のコマンドで各シークレットを設定:

```bash
wrangler secret put LARK_APP_ID
# → cli_a92d697b1df89e1b を入力

wrangler secret put LARK_APP_SECRET
# → automation_config.json の app_secret を入力

wrangler secret put LARK_VERIFICATION_TOKEN
# → Lark管理コンソールから取得（手順5参照）

wrangler secret put LARK_ENCRYPT_KEY
# → Lark管理コンソールから取得（オプション、空でもOK）

wrangler secret put GITHUB_TOKEN
# → 手順6で作成するPATを入力

wrangler secret put GITHUB_REPO
# → yosukekuni/tas-automation

wrangler secret put ALLOWED_OPEN_ID
# → ou_d2e2e520a442224ea9d987c6186341ce
```

## 5. Lark管理コンソールでEvent Subscription設定

1. https://open.larksuite.com/app/ にアクセス
2. 「TAS-Automation」アプリを選択
3. 左メニュー「Event Subscriptions」（イベント購読）をクリック
4. 「Request URL」に手順3のWorker URLを入力:
   ```
   https://tas-lark-bot.<account>.workers.dev
   ```
5. 「Verification Token」と「Encrypt Key」をコピーして手順4のSecrets設定に使用
6. 「Add Event」で以下を追加:
   - `im.message.receive_v1`（メッセージ受信イベント）
7. 必要な権限を確認:
   - `im:message` (メッセージ読み取り)
   - `im:message:send_as_bot` (Bot としてメッセージ送信)
8. 保存してURLの検証を実行（challengeレスポンスが自動的に返される）

## 6. GitHub Personal Access Token作成

1. https://github.com/settings/tokens にアクセス
2. 「Generate new token (classic)」をクリック
3. 設定:
   - Note: `TAS Lark Bot Dispatcher`
   - Expiration: 90 days（期限切れ前に再発行）
   - Scopes: `repo` にチェック
4. 生成されたトークンをコピーして手順4の `GITHUB_TOKEN` に設定
5. GitHub Actions Secretsにも追加:
   - リポジトリ Settings → Secrets and variables → Actions
   - `GITHUB_TOKEN` は予約語のため使えない場合は `GH_PAT` 等で設定

## 7. テスト

### a. challenge検証テスト

```bash
curl -X POST https://tas-lark-bot.<account>.workers.dev \
  -H "Content-Type: application/json" \
  -d '{"type": "url_verification", "challenge": "test123"}'
```

期待される応答:
```json
{"challenge": "test123"}
```

### b. Lark DMテスト

携帯のLarkアプリで TAS-Automation Bot に以下を送信:
- 「CRM状況」→ 商談ステージ別サマリが返ってくる
- 「サイトチェック」→ 主要ページのステータスが返ってくる
- 「入札情報」→ bid_scanner.py が実行される

### c. GitHub Actions確認

GitHub リポジトリの Actions タブで `Lark Command Executor` ワークフローが
起動していることを確認。

## トラブルシューティング

### Worker URLの検証が失敗する
- `wrangler tail` でリアルタイムログを確認
- challengeレスポンスの形式を確認

### GitHub Actionsが起動しない
- PATの `repo` スコープを確認
- `wrangler tail` でdispatchエラーを確認
- リポジトリ名が正しいか確認

### Lark DMの返信が来ない
- Lark管理コンソールでBot権限 (`im:message:send_as_bot`) を確認
- GitHub Actions のログを確認

### 長文が途切れる
- Lark DM は1メッセージ2000文字制限
- 自動分割送信されるが、非常に長い結果はClaude APIで要約される

## 費用

- Cloudflare Workers Free: 100,000リクエスト/日（十分）
- GitHub Actions: パブリックリポジトリは無料、プライベートは2,000分/月
- Claude API: コマンド解釈(入力) + 要約(出力) で1回あたり約$0.01-0.05
