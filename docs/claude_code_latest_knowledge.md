# Claude Code 最新知見レポート (2026-03-15)

## 1. CLAUDE.mdのベストプラクティス

### 基本原則
- **200行以内に抑える**: フロンティアモデルは約150-200の指示に従える。Claude Codeのシステムプロンプトで約50消費するため、ユーザー指示は100-150が限度
- **`/init`で初期生成**: コードベースを分析してビルドシステム・テストフレームワーク・コードパターンを検出してくれる
- **コードのように管理**: 問題が起きたらレビュー、定期的に剪定、行動変化を観察してテスト
- **gitにチェックイン**: チーム共有で価値が複利的に増加

### 含めるべき内容
| 含める | 含めない |
|--------|----------|
| Claudeが推測できないBashコマンド | コードを読めば分かること |
| デフォルトと異なるコードスタイルルール | 標準的な言語規約 |
| テスト手順・推奨テストランナー | 詳細なAPIドキュメント（リンクで代替） |
| リポジトリ作法（ブランチ命名、PR規約） | 頻繁に変わる情報 |
| プロジェクト固有のアーキテクチャ決定 | 長い説明やチュートリアル |
| 開発環境の癖（必須env vars） | ファイルごとのコードベース説明 |
| 非自明な落とし穴 | 「クリーンなコードを書く」等の自明な指示 |

### 強調テクニック
- 重要度を上げるには「IMPORTANT」「YOU MUST」等を追加
- Claudeが何度もルールを無視する場合 → ファイルが長すぎて指示が埋もれている
- Claudeがclaude.mdの内容を質問してくる場合 → 表現が曖昧

### ファイル配置
- `~/.claude/CLAUDE.md`: 全セッション共通
- `./CLAUDE.md`: プロジェクトルート（git共有）
- 親ディレクトリ: モノレポ構成で自動読み込み
- 子ディレクトリ: 該当ファイル作業時にオンデマンド読み込み

### インポート構文
```markdown
See @README.md for project overview and @package.json for available npm commands.
# Additional Instructions
- Git workflow: @docs/git-instructions.md
- Personal overrides: @~/.claude/my-project-instructions.md
```

---

## 2. プロンプトエンジニアリングのコツ

### 最高レバレッジ: 検証手段を提供する
- テスト・スクリーンショット・期待出力を含める
- 「テストを書いて実行して」が最も効果的
- UIはChrome拡張で視覚検証可能

### 4フェーズワークフロー
1. **Explore**: Plan Modeでファイルを読み理解（変更なし）
2. **Plan**: 詳細な実装計画を作成（Ctrl+Gでエディタで直接編集可能）
3. **Implement**: Normal Modeで実装、計画に対して検証
4. **Commit**: 説明的なメッセージでコミット・PR作成

### 効果的なプロンプトパターン
- **スコープ指定**: 「foo.pyのテスト追加」→「foo.pyのユーザーログアウト時のエッジケースのテストを書く。モック不使用」
- **ソース指示**: 「APIが変な理由は？」→「ExecutionFactoryのgit historyを見てAPIの経緯をまとめて」
- **パターン参照**: 「カレンダーウィジェット追加」→「HotDogWidget.phpのパターンに従って新しいカレンダーウィジェットを実装」
- **症状記述**: 「ログインバグ修正」→「セッションタイムアウト後にログイン失敗。src/auth/のトークンリフレッシュを調査」

### リッチコンテンツ提供
- `@`でファイル参照
- 画像をコピー/ペーストまたはドラッグ&ドロップ
- URLで外部ドキュメント参照
- `cat error.log | claude`でデータパイプ
- `/permissions`で頻繁に使うドメインを許可リスト化

### インタビュー方式（大きな機能向け）
```
I want to build [brief description]. Interview me in detail using the AskUserQuestion tool.
Ask about technical implementation, UI/UX, edge cases, concerns, and tradeoffs.
Don't ask obvious questions, dig into the hard parts I might not have considered.
Keep interviewing until we've covered everything, then write a complete spec to SPEC.md.
```
→ spec完成後、新規セッションで実装（クリーンコンテキスト）

---

## 3. コンテキスト管理の最適化

### 核心原則
**コンテキストウィンドウが埋まると性能が劣化する** — これが最も重要なリソース管理

### 1Mコンテキスト（Opus 4.6）
- Max/Team/Enterpriseプランで自動的に有効
- Opus 4.6とSonnet 4.6で利用可能
- 無効化: `CLAUDE_CODE_DISABLE_1M_CONTEXT=1`

### コンテキスト節約テクニック
- **Plan Mode活用**: トークン消費を半減
- **PreCompact hooks**: コンパクション時の重要情報損失を30%削減
- **コンパクション閾値**: 85%に設定すると95%より平均2.3秒レスポンス改善
- **ファイル部分読み込み**: `--lines`オプションで関連行のみ読み込み（トークン70%節約）
- **grepを優先**: 200トークン vs フルファイル3,000トークン
- **30分スプリント**: 機能/修正ごとに区切り、間に`/compact`実行 → 4時間で85%性能維持

### セッション管理
- `/clear`: 無関係タスク間でコンテキストリセット
- `/compact <instructions>`: 指示付きコンパクション（例: `/compact Focus on the API changes`）
- `/rewind` or `Esc+Esc`: チェックポイントに戻る（会話/コードを選択復元）
- `/btw`: コンテキストに残らないサイドクエスチョン
- `/cost`: 現在のトークン消費量確認
- `/rename`: セッションに名前付け（例: "oauth-migration"）

### 修正の黄金ルール
- 2回修正しても直らない → `/clear`して、学びを含めたより良いプロンプトで再開
- クリーンセッション＋良いプロンプト >> 長いセッション＋蓄積された修正

---

## 4. Skills・Hooks・Subagentsの使い方

### Skills（.claude/skills/SKILL.md）
- **確率的**: Claudeが判断して使用するかどうか決める
- オンデマンドロード（CLAUDE.mdと違い全セッションにロードされない）
- `disable-model-invocation: true`で手動呼び出し専用

```yaml
# .claude/skills/fix-issue/SKILL.md
---
name: fix-issue
description: Fix a GitHub issue
disable-model-invocation: true
---
Analyze and fix the GitHub issue: $ARGUMENTS.
1. Use `gh issue view` to get the issue details
2. Search the codebase for relevant files
3. Implement the fix
4. Write and run tests
5. Create a descriptive commit
6. Push and create a PR
```

### Hooks（.claude/settings.json）
- **決定的**: 例外なく毎回実行
- イベント: `PreToolUse`, `PostToolUse`, `Notification`, `Stop`, `UserPromptSubmit`, `SessionStart`, `PostCompact`, `Elicitation`, `ElicitationResult`, `SubagentStart`, `SubagentStop`, `TeammateIdle`, `TaskCompleted`
- **HTTP hooks**: URLにPOST可能（v2.1.63+）

```json
{
  "hooks": {
    "PostToolUse": [{
      "matcher": "Edit|Write",
      "hooks": [{"type": "command", "command": "./scripts/run-linter.sh"}]
    }],
    "PreToolUse": [{
      "matcher": "Bash",
      "hooks": [{"type": "command", "command": "./scripts/validate-command.sh"}]
    }]
  }
}
```

### Custom Subagents（.claude/agents/）
- 独立コンテキストウィンドウで実行
- ツールアクセス制限可能
- モデル選択可能（sonnet/opus/haiku/inherit）
- **persistent memory**: `user`/`project`/`local`スコープで学習蓄積

```markdown
# .claude/agents/security-reviewer.md
---
name: security-reviewer
description: Reviews code for security vulnerabilities
tools: Read, Grep, Glob, Bash
model: opus
memory: user
---
You are a senior security engineer. Review code for:
- Injection vulnerabilities
- Authentication and authorization flaws
- Secrets or credentials in code
- Insecure data handling
```

### Agent Teams（実験的機能）
- 複数Claude Codeインスタンスが協調動作
- `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`で有効化
- リード1名＋チームメイト複数名
- 共有タスクリスト＋メッセージングシステム
- 3-5名が最適（1名あたり5-6タスク目安）

---

## 5. Mac mini常駐構成

### launchd daemon構成
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.tas.claude-agent</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/claude</string>
        <string>-p</string>
        <string>Process pending tasks from queue</string>
        <string>--allowedTools</string>
        <string>Read,Edit,Bash,Grep,Glob</string>
        <string>--output-format</string>
        <string>json</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/path/to/project</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/var/log/claude-agent.log</string>
    <key>StandardErrorPath</key>
    <string>/var/log/claude-agent-error.log</string>
</dict>
</plist>
```

### 24/7運用設定
- System Settings > Battery > Power Adapter > 自動スリープ無効
- ディスプレイタイムアウト: Never
- 「停電後自動再起動」有効化
- 消費電力: アイドル15W / AI負荷30W → 月$3-5

### headlessモード（claude -p）の高度な使い方
```bash
# 基本: 1回限りのクエリ
claude -p "Explain what this project does"

# 構造化出力
claude -p "List all API endpoints" --output-format json

# JSONスキーマ付き構造化出力
claude -p "Extract function names" --output-format json \
  --json-schema '{"type":"object","properties":{"functions":{"type":"array","items":{"type":"string"}}}}'

# ストリーミング
claude -p "Analyze this log file" --output-format stream-json --verbose --include-partial-messages

# 会話継続
session_id=$(claude -p "Start review" --output-format json | jq -r '.session_id')
claude -p "Continue review" --resume "$session_id"

# システムプロンプトカスタマイズ
claude -p --append-system-prompt "You are a security engineer." --output-format json

# ファンアウト（大規模マイグレーション）
for file in $(cat files.txt); do
  claude -p "Migrate $file" --allowedTools "Edit,Bash(git commit *)"
done
```

### タスクキュー方式の実装例
```bash
#!/bin/bash
# task_queue_processor.sh
QUEUE_DIR="/path/to/queue"
DONE_DIR="/path/to/done"

while true; do
  for task_file in "$QUEUE_DIR"/*.json; do
    [ -f "$task_file" ] || continue
    prompt=$(jq -r '.prompt' "$task_file")
    tools=$(jq -r '.allowed_tools' "$task_file")

    result=$(claude -p "$prompt" \
      --allowedTools "$tools" \
      --output-format json 2>&1)

    echo "$result" > "$DONE_DIR/$(basename "$task_file")"
    mv "$task_file" "$DONE_DIR/$(basename "$task_file" .json).task.json"
  done
  sleep 30
done
```

---

## 6. GitHub Actions + Claude Code

### 公式アクション: anthropics/claude-code-action
```yaml
name: Claude Code Review
on:
  pull_request:
    types: [opened, synchronize]
  issue_comment:
    types: [created]

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: anthropics/claude-code-action@v1
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
```

### 自動化パターン
- `@claude`メンションでPR/Issue対応
- Issue → PR自動生成ワークフロー
- スケジュールメンテナンス（リポジトリヘルスチェック）
- Issue自動トリアージ＆ラベリング
- ドキュメント同期
- セキュリティフォーカスレビュー
- リリースノート自動生成

---

## 7. MCP（Model Context Protocol）最新動向

### MCP Elicitation（v2.1.76, 2026-03-14）
- MCPサーバーがタスク中にインタラクティブダイアログで構造化入力を要求可能
- `Elicitation`/`ElicitationResult`フックで応答をインターセプト/オーバーライド

### Tool Search（遅延ロード）
- コンテキスト使用量を最大95%削減
- MCPサーバーのツール数が多くてもコンテキスト限度を心配不要

### claude.ai MCP connectors
- v2.1.46+ でClaude Code内からclaude.aiのMCPコネクタを利用可能

### OAuth対応
- MCP OAuth step-up auth + discovery caching
- トークン自動リフレッシュ

---

## 8. 最新アップデート（2026年2-3月）

### Opus 4.6関連
- v2.1.68: デフォルトeffortがmediumに
- v2.1.36: Fast Modeが利用可能に
- v2.1.75: Max/Team/Enterprise向け1Mコンテキストがデフォルト
- Opus 4, 4.1はファーストパーティAPIから削除 → Opus 4.6に自動マイグレーション
- 「ultrathink」キーワードで次のターンをhigh effortに

### 新コマンド/機能
- `/loop`: 定期的にプロンプト/スラッシュコマンドを繰り返し実行
- `/effort`: effortレベル設定（low/medium/high）→ ○ ◐ ●
- `/context`: コンテキスト負荷の最適化提案を表示
- `/color`: セッションカラーカスタマイズ
- `/plan <description>`: 説明付きでplan mode即開始
- Auto-Memory: Claudeが自動的に有用コンテキストをauto-memoryに保存
- Voice STT: 20言語対応
- Worktree Isolation: エージェントにgit worktreeで隔離環境提供

### パフォーマンス改善
- 起動時のWASM/UIインポート遅延ロード
- 長時間セッションのメモリリーク修正多数
- バンドルサイズ約510KB削減
- ベースラインメモリ約16MB削減

---

## 9. よくある失敗パターンと対策

| パターン | 説明 | 対策 |
|---------|------|------|
| Kitchen Sink Session | 1セッションで無関係タスクを次々 | タスク間で`/clear` |
| 繰り返し修正 | 何度も修正指示して文脈汚染 | 2回失敗したら`/clear`＋より良いプロンプト |
| CLAUDE.md肥大化 | 長すぎて指示が無視される | 徹底的に剪定。正しい行動をデフォルトでするならその指示は削除 |
| Trust-then-Verify Gap | もっともらしい実装だがエッジケース未対応 | 必ず検証手段提供（テスト・スクリプト） |
| Infinite Exploration | スコープなしの「調査して」で大量ファイル読み | スコープ限定 or サブエージェント使用 |

---

## 10. TASプロジェクトへの適用推奨

### 即座に実行可能
1. **CLAUDE.mdの最適化**: 現在のMEMORY.mdをレビューし、200行以内に整理。domain knowledgeはSkillsに移行
2. **PreCompact hook導入**: 重要情報（タスクBase ID、CRM構造等）がコンパクション時に保持されるよう設定
3. **Subagents導入**: security-reviewer, code-reviewerをプロジェクトに追加
4. **Hooks導入**: PostToolUseでlint自動実行、PreToolUseでreview_agent自動実行

### Mac mini購入後
5. **launchd daemon設定**: タスクキュー方式でLark Base監視 → 自動実行
6. **Agent Teams活用**: 複雑タスクで3-5エージェント並列実行
7. **MCP Server統合**: Lark CRM直接操作用のカスタムMCPサーバー構築

### 月次リサーチ時の確認ポイント
- https://code.claude.com/docs/en/changelog
- https://github.com/anthropics/claude-code/releases
- https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md
- Claude公式ブログ: https://www.anthropic.com/engineering

---

## Sources
- [Best Practices for Claude Code](https://code.claude.com/docs/en/best-practices)
- [Claude Code Changelog](https://code.claude.com/docs/en/changelog)
- [Run Claude Code programmatically](https://code.claude.com/docs/en/headless)
- [Create custom subagents](https://code.claude.com/docs/en/sub-agents)
- [Orchestrate teams of Claude Code sessions](https://code.claude.com/docs/en/agent-teams)
- [CLAUDE.md Best Practices - UX Planet](https://uxplanet.org/claude-md-best-practices-1ef4f861ce7c)
- [Claude Code Ultimate Guide - GitHub](https://github.com/FlorianBruniaux/claude-code-ultimate-guide)
- [Claude Code Setup Guide: MCP, Hooks, Skills](https://okhlopkov.com/claude-code-setup-mcp-hooks-skills-2026/)
- [Awesome Claude Code](https://github.com/hesreallyhim/awesome-claude-code)
- [Claude Code Showcase](https://github.com/ChrisWiles/claude-code-showcase)
- [Claude Agent SDK](https://platform.claude.com/docs/en/agent-sdk/overview)
- [Claude Code as MCP Server](https://github.com/steipete/claude-code-mcp)
- [Building agents with Claude Agent SDK](https://www.anthropic.com/engineering/building-agents-with-the-claude-agent-sdk)
- [Mac Mini 24/7 Autonomous Agent](https://medium.com/@akhil.reji141/the-ai-proof-infrastructure-converting-a-mac-mini-into-a-24-7-autonomous-agent-4eef4940942c)
- [Claude Code GitHub Actions](https://code.claude.com/docs/en/github-actions)
