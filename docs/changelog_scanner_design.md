# Changelog自動スキャン設計

作成日: 2026-03-14 / ステータス: 凍結（設計書のみ）

## 概要

GitHub Actions週次ワークフローで、Claude Code関連の新機能・ベストプラクティス・MCP情報を自動スキャンし、Lark通知する。

## スキャン対象

| ソース | URL/方法 | 取得方法 |
|--------|----------|----------|
| Anthropic公式ブログ | https://www.anthropic.com/news | RSSフィード or WebスクレイピングAPI |
| Claude Code Changelog | https://docs.anthropic.com/en/docs/claude-code/changelog | HTTPフェッチ+差分検知 |
| Hacker News | HN Algolia API (`search_by_date?query=claude`) | REST API |
| X (Twitter) | @AnthropicAI, #ClaudeCode | API（レートリミット注意） |
| Zenn | https://zenn.dev/topics/claude | RSSフィード |
| GitHub Releases | anthropics/claude-code | GitHub API |

## アーキテクチャ

```
GitHub Actions (毎週日曜 9:00 JST)
  ↓
changelog_scanner.py
  ├→ 各ソースからデータ取得
  ├→ 前回スキャンとの差分抽出（state.jsonで管理）
  ├→ Claude APIで要約・分類
  └→ Lark Webhook通知
```

### changelog_scanner.py 構成

```python
# 1. 各ソースフェッチャー
def fetch_anthropic_blog(): ...
def fetch_changelog(): ...
def fetch_hackernews(): ...
def fetch_zenn(): ...

# 2. 差分検知
def detect_new_items(current, previous_state): ...

# 3. Claude API要約
def summarize_updates(items): ...
#    → 「TAS業務への影響度」をスコアリング（高/中/低）

# 4. Lark通知
def notify_lark(summary): ...
```

### Lark通知フォーマット

```
📡 Claude Code週次アップデート (2026-03-14)

【高影響】
- MCP: 新しいサーバープロトコルv2リリース → CRM連携に活用可能
- Hooks: pre-tool-useフック追加 → セキュリティ強化に使える

【中影響】
- パフォーマンス改善: コンテキストウィンドウ拡大
- 新ツール: ...

【参考】
- コミュニティ: Zennで○○の記事が話題
```

### GitHub Actions Workflow

```yaml
# .github/workflows/changelog_scanner.yml
name: Changelog Scanner
on:
  schedule:
    - cron: '0 0 * * 0'  # 毎週日曜 09:00 JST
  workflow_dispatch:

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install requests
      - run: python scripts/changelog_scanner.py
        env:
          CLAUDE_API_KEY: ${{ secrets.CLAUDE_API_KEY }}
          LARK_WEBHOOK_URL: ${{ secrets.LARK_WEBHOOK_URL }}
```

## 状態管理

- `data/changelog_scanner_state.json` にスキャン済みURL/IDを保存
- Git管理してActions間で永続化

## 工数見積もり

| 作業 | 工数 |
|------|------|
| changelog_scanner.py | 4時間 |
| 各ソースフェッチャー | 3時間 |
| Claude API要約ロジック | 1時間 |
| GitHub Actions workflow | 30分 |
| テスト | 1.5時間 |
| **合計** | **10時間** |

## 優先順位

**低**: 情報収集は手動でも可能。売上直結ではない。ただしClaude Codeの進化速度が速いため、機会損失を防ぐ意味で余裕時に実装したい。
