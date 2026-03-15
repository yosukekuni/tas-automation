# GitHub Actions CI: Claude Code Review 自動化設計

## 概要

PR作成・push時に `claude -p`（headless mode）で `review_agent.py` のデプロイチェックを自動実行し、結果をPRコメントに投稿する。

---

## 1. ワークフロー設計

### トリガー

```yaml
on:
  pull_request:
    types: [opened, synchronize, reopened]
    branches: [main]
  push:
    branches: [main]
```

- **PR時**: レビュー結果をPRコメントとして投稿。CRITICALがあればステータスチェック失敗
- **push to main時**: デプロイチェックのみ実行。NG時はLark通知

### ワークフローファイル

```yaml
# .github/workflows/code_review.yml
name: Code Review (Claude)

on:
  pull_request:
    types: [opened, synchronize, reopened]
    branches: [main]

permissions:
  contents: read
  pull-requests: write

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # diff取得のため全履歴

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Setup config
        env:
          LARK_APP_ID: ${{ secrets.LARK_APP_ID }}
          LARK_APP_SECRET: ${{ secrets.LARK_APP_SECRET }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          LARK_WEBHOOK_URL: ${{ secrets.LARK_WEBHOOK_URL }}
        run: python scripts/setup_config.py

      - name: Get changed files
        id: changed
        run: |
          # PR内の変更ファイル一覧
          git diff --name-only ${{ github.event.pull_request.base.sha }}..HEAD > /tmp/changed_files.txt
          cat /tmp/changed_files.txt

          # 変更内容の差分
          git diff ${{ github.event.pull_request.base.sha }}..HEAD > /tmp/full_diff.txt

          # ファイル数
          echo "count=$(wc -l < /tmp/changed_files.txt)" >> "$GITHUB_OUTPUT"

      - name: Run deploy review
        id: review
        run: |
          # review_agent.py の deploy プロファイルで差分をチェック
          python -c "
          import json, sys
          sys.path.insert(0, 'scripts')
          from review_agent import review

          with open('/tmp/full_diff.txt') as f:
              diff_content = f.read()

          if not diff_content.strip():
              print('No changes to review')
              result = {'verdict': 'OK', 'issues': [], 'summary': 'No changes detected'}
          else:
              result = review('deploy', diff_content, output_json=True)

          with open('/tmp/review_result.json', 'w') as f:
              json.dump(result, f, ensure_ascii=False, indent=2)

          print(json.dumps(result, ensure_ascii=False, indent=2))
          # exit codeは設定しない（後のステップでコメント投稿するため）
          "

      - name: Post PR comment
        if: always() && github.event_name == 'pull_request'
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const result = JSON.parse(fs.readFileSync('/tmp/review_result.json', 'utf8'));
            const changedFiles = fs.readFileSync('/tmp/changed_files.txt', 'utf8').trim();

            const icon = result.verdict === 'OK' ? ':white_check_mark:' : ':x:';
            let body = `## ${icon} Code Review (review_agent)\n\n`;
            body += `**Verdict**: ${result.verdict}\n`;
            body += `**Summary**: ${result.summary}\n\n`;

            if (result.issues && result.issues.length > 0) {
              body += `### Issues\n\n`;
              for (const issue of result.issues) {
                const sevIcon = issue.severity === 'CRITICAL' ? ':red_circle:' : ':yellow_circle:';
                body += `${sevIcon} **[${issue.severity}]** Check #${issue.check_number}: ${issue.description}\n`;
                if (issue.fix_suggestion) {
                  body += `  - Fix: ${issue.fix_suggestion}\n`;
                }
                body += `\n`;
              }
            }

            body += `\n<details><summary>Changed files</summary>\n\n\`\`\`\n${changedFiles}\n\`\`\`\n</details>\n`;
            body += `\n---\n_Reviewed by review_agent.py (deploy profile) via Claude Haiku_`;

            // 既存のbotコメントを探して更新（重複防止）
            const comments = await github.rest.issues.listComments({
              owner: context.repo.owner,
              repo: context.repo.repo,
              issue_number: context.issue.number,
            });
            const botComment = comments.data.find(c =>
              c.body.includes('Code Review (review_agent)')
            );

            if (botComment) {
              await github.rest.issues.updateComment({
                owner: context.repo.owner,
                repo: context.repo.repo,
                comment_id: botComment.id,
                body: body,
              });
            } else {
              await github.rest.issues.createComment({
                owner: context.repo.owner,
                repo: context.repo.repo,
                issue_number: context.issue.number,
                body: body,
              });
            }

            // CRITICALがあればfail
            const hasCritical = result.issues?.some(i => i.severity === 'CRITICAL');
            if (hasCritical) {
              core.setFailed('CRITICAL issues found in review');
            }
```

---

## 2. claude -p を使う場合（拡張版）

現在の `review_agent.py` は Claude API を直接呼んでいるため、`claude -p` は不要。
将来的に `claude -p` でより高度なレビューを行う場合の設計を示す。

### claude CLI のインストールとAPI Key設定

```yaml
      - name: Install Claude CLI
        run: |
          npm install -g @anthropic-ai/claude-code

      - name: Run Claude review
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          # claude -p でheadlessレビュー実行
          DIFF=$(git diff ${{ github.event.pull_request.base.sha }}..HEAD)
          REVIEW=$(claude -p "以下のgit diffをreview_agent.pyのdeployプロファイル基準でレビューしてください。
          秘密情報（API key, password）がコミットに含まれていないか、
          automation_config.jsonや.envがコミット対象に入っていないか確認。
          JSON形式で結果を返してください。

          ${DIFF}")
          echo "$REVIEW" > /tmp/review_result.json
```

### claude -p の制約事項

| 項目 | 詳細 |
|------|------|
| コスト | Opus: ~$15/100万input tokens, Sonnet: ~$3/100万input tokens |
| レート制限 | API tier依存。CI向けにはHaikuで十分 |
| タイムアウト | GitHub Actions jobは6時間上限。claude -pは通常数十秒で完了 |
| 入力サイズ | 大きなdiffは切り詰め必要（200KBを超えるdiffは要約化） |

### 推奨: API直接呼び出し（現行方式の維持）

`review_agent.py` が既にClaude Haiku APIを直接呼んでおり、以下の理由でこの方式を推奨:

1. **コスト効率**: Haiku ($0.25/100万tokens) << claude -p (Sonnet/Opusベース)
2. **依存性**: Node.js + claude CLIインストール不要
3. **制御性**: プロファイル別チェック項目をPython側で管理可能
4. **速度**: API直接 < CLI経由

---

## 3. Secrets管理

### 必要なSecrets（既にリポジトリに設定済み）

| Secret名 | 用途 | 設定状態 |
|-----------|------|----------|
| `ANTHROPIC_API_KEY` | review_agent.py Claude API呼び出し | setup_config.py対応済み |
| `LARK_APP_ID` | Lark通知 | 設定済み |
| `LARK_APP_SECRET` | Lark通知 | 設定済み |
| `LARK_WEBHOOK_URL` | Lark通知 | 設定済み |

### 追加設定不要

`setup_config.py` が環境変数からconfig生成する仕組みが既に稼働しているため、新規Secret追加は不要。`ANTHROPIC_API_KEY` が未設定の場合のみ追加が必要。

### 確認コマンド

```bash
gh secret list -R yosukekuni/tas-automation
```

---

## 4. セキュリティ

### API Key漏洩防止

1. **Secretsは自動マスク**: GitHub Actionsはログ中のSecret値を `***` に置換
2. **fork PRの制限**: `pull_request_target` は使わない。fork PRにはSecretsが渡らないデフォルト動作を維持
3. **automation_config.json**: `.gitignore` に含まれており、setup_config.pyが実行時に動的生成。コミットされない
4. **diff内容**: review_agent.pyが `deploy` プロファイルで秘密情報混入を自動チェック

### 追加対策

```yaml
      # PRがforkからの場合はスキップ（Secret保護）
      - name: Check fork
        if: github.event.pull_request.head.repo.fork == true
        run: |
          echo "Skipping review for fork PR (no secrets available)"
          exit 0
```

---

## 5. コスト見積もり

### GitHub Actions 無料枠

| プラン | 無料枠 | 現在使用量（推定） |
|--------|--------|-------------------|
| Free | 2,000分/月 | ~1,500分/月（15min cron多数） |
| Pro ($4/月) | 3,000分/月 | - |

### CI追加による増分

| 条件 | 見積もり |
|------|----------|
| PR頻度 | 月10-20回（手動push中心） |
| 1回のCI実行時間 | 約1-2分（checkout + python + API call） |
| 月間追加 | 最大40分 |
| 無料枠への影響 | 軽微（2%程度の増加） |

### Claude API コスト

| モデル | 料金 | 1回のレビュー | 月間（20回） |
|--------|------|--------------|-------------|
| Haiku 3.5 | $0.25/$1.25 per 1M tokens | ~$0.002 | ~$0.04 |
| claude -p (Sonnet) | $3/$15 per 1M tokens | ~$0.02 | ~$0.40 |

**結論**: Haiku APIで月$0.04以下。GitHub Actions枠も余裕あり。追加コストは実質ゼロ。

---

## 6. 実装手順

### Step 1: ANTHROPIC_API_KEY の確認

```bash
gh secret list -R yosukekuni/tas-automation | grep ANTHROPIC
# なければ追加:
# gh secret set ANTHROPIC_API_KEY -R yosukekuni/tas-automation
```

### Step 2: ワークフローファイル作成

`.github/workflows/code_review.yml` を上記の内容で作成。

### Step 3: テスト

```bash
# テスト用ブランチでPRを作成
git checkout -b test/ci-review
echo "# test" >> README.md
git add README.md
git commit -m "test: CI review trigger"
git push -u origin test/ci-review
gh pr create --title "Test CI review" --body "CI review test"
```

### Step 4: 動作確認項目

- [ ] PRコメントにレビュー結果が投稿される
- [ ] CRITICALがある場合、ステータスチェックが失敗する
- [ ] Secret値がログに表示されない
- [ ] 再pushでコメントが更新される（重複しない）

---

## 7. 将来の拡張

### Phase 2: プロファイル自動選択

変更ファイルの種類に応じて適切なレビュープロファイルを自動選択:

```python
# 変更ファイルから自動判定
profiles = set()
for f in changed_files:
    if f.endswith('.css') or 'snippet' in f:
        profiles.add('css')
    if f.endswith('.html'):
        profiles.add('article')
    if 'crm' in f or 'lark' in f:
        profiles.add('crm')
profiles.add('deploy')  # 常に実行
```

### Phase 3: claude -p による高度レビュー

CRITICALが見つかった場合のみ、claude -p (Sonnet) で詳細分析 + 修正案の自動生成:

```yaml
      - name: Deep review (on CRITICAL only)
        if: steps.review.outputs.has_critical == 'true'
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          npm install -g @anthropic-ai/claude-code
          claude -p "このdiffにCRITICALな問題が見つかりました。修正パッチを生成してください。" \
            < /tmp/full_diff.txt > /tmp/fix_suggestion.md
```

### Phase 4: Required Status Check

リポジトリ設定でこのCIをmainブランチへのマージ必須条件にする:

```
Settings > Branches > Branch protection rules > main
  [x] Require status checks to pass before merging
  [x] code_review / review
```
