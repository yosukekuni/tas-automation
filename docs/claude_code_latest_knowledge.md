# Claude Code 最新知見レポート (2026-03-16)

> 前回: 2026-03-15 / 現在インストール版: v2.1.76

---

## 1. 最新バージョン・機能アップデート（2026年3月時点）

### v2.1.76（2026-03-14）— 最新安定版
- **MCP Elicitation**: MCPサーバーがタスク中にインタラクティブダイアログで構造化入力を要求可能。`Elicitation`/`ElicitationResult`フックで応答をインターセプト/オーバーライド
- **CLIフラグ `-n` / `--name`**: セッション起動時に表示名を設定
- **worktree.sparsePaths**: 大規模モノレポでgit sparse-checkoutにより必要ディレクトリのみチェックアウト
- **PostCompactフック**: コンパクション完了後に発火する新フックイベント
- **`/effort`コマンド**: モデルeffortレベル設定（low/medium/high）。表示: ○ ◐ ●
- **セッション品質サーベイ**: Enterprise管理者が`feedbackSurveyRate`で設定可能
- **バグ修正**: ToolSearchの遅延ロードツールがコンパクション後にスキーマを失う問題を修正

### 2026年3月の主要アップデート総括（v2.1.63〜v2.1.76）
| 機能 | バージョン | 概要 |
|------|-----------|------|
| HTTP hooks | v2.1.63 | URLにPOSTでフックイベント送信 |
| Voice STT | v2.1.64 | `/voice`で20言語対応の音声入力（push-to-talk） |
| `/loop` | v2.1.65 | 定期的にプロンプト/コマンドを繰り返し実行（cronライク） |
| Fast Mode | v2.1.36 | Opus 4.6でFast Mode利用可能 |
| Default effort=medium | v2.1.68 | Opus 4.6のデフォルトeffortがmediumに変更 |
| `/color` | v2.1.70 | セッションカラーカスタマイズ |
| 1Mコンテキスト | v2.1.75 | Max/Team/Enterprise向けにOpus 4.6で1Mコンテキストがデフォルト有効 |
| MCP Elicitation | v2.1.76 | MCPサーバーからの構造化入力要求 |
| PostCompact hook | v2.1.76 | コンパクション後フック |

### Opus 4.6 モデル関連
- Opus 4, 4.1はファーストパーティAPIから削除 → Opus 4.6に自動マイグレーション
- 「ultrathink」キーワードで次のターンをhigh effortに強制
- 1Mコンテキスト（Max/Team/Enterprise）。無効化: `CLAUDE_CODE_DISABLE_1M_CONTEXT=1`
- Firefox脆弱性22件をOpus 4.6が2週間で発見（Anthropic+Mozilla共同研究）

---

## 2. Hooks完全ガイド（3タイプ+HTTPの実践パターン）

### フックタイプ一覧
| タイプ | 説明 | 用途 |
|--------|------|------|
| `command` | シェルコマンド実行。JSON入力をstdinで受信 | lint, セキュリティチェック, ファイル保護 |
| `prompt` | Claudeモデルへの単発評価。`$ARGUMENTS`プレースホルダー | アーキテクチャパターン検証, コンテキスト注入 |
| `agent` | サブエージェント起動（Read,Grep,Glob等のツールアクセス） | 深い検証, コードレビュー |
| `http` | URLにPOST（v2.1.63+）。commandと同じJSONをbodyで送信 | 外部サービス連携, ログ収集 |

### 12のフックイベント
1. **SessionStart** — セッション開始時（commandタイプのみ対応）
2. **UserPromptSubmit** — プロンプト送信前（matcherなし、全プロンプトにトリガー）
3. **PreToolUse** — ツール実行前。**唯一アクションをブロック可能**
4. **PostToolUse** — ツール実行後
5. **Notification** — 通知時
6. **Stop** — セッション停止時
7. **PostCompact** — コンパクション完了後（v2.1.76で追加）
8. **Elicitation** — MCP Elicitation要求時（v2.1.76）
9. **ElicitationResult** — Elicitation応答時（v2.1.76）
10. **SubagentStart** / **SubagentStop** — サブエージェント開始/停止
11. **TeammateIdle** — チームメイトがアイドル状態
12. **TaskCompleted** — タスク完了時

### 実践パターン（TAS向け推奨）
```json
{
  "hooks": {
    "PostToolUse": [{
      "matcher": "Edit|Write",
      "hooks": [{"type": "command", "command": "python3 scripts/review_agent.py lint"}]
    }],
    "PreToolUse": [{
      "matcher": "Bash",
      "hooks": [{"type": "command", "command": "python3 scripts/validate_command.sh"}]
    }],
    "PostCompact": [{
      "hooks": [{"type": "prompt", "prompt": "重要情報を確認: Lark Base ID, CRM構造, タスク管理テーブルIDが保持されているか検証してください"}]
    }],
    "Stop": [{
      "hooks": [{"type": "command", "command": "python3 scripts/session_save.py"}]
    }]
  }
}
```

### データフローの重要な注意
- commandフックはstdinでJSONを受信（環境変数ではない）
- `$CLAUDE_TOOL_INPUT`や`$CLAUDE_TOOL_NAME`の環境変数は存在しない
- exit code 0=成功, 非0=ブロック（PreToolUseのみ）

---

## 3. Subagents・Agent Teams・Worktree

### Custom Subagents（.claude/agents/）
```markdown
# .claude/agents/security-reviewer.md
---
name: security-reviewer
description: Reviews code for security vulnerabilities
tools: Read, Grep, Glob, Bash
model: opus
memory: user
---
You are a senior security engineer...
```
- 独立コンテキストウィンドウで実行
- ツールアクセス制限可能
- モデル選択: sonnet/opus/haiku/inherit
- persistent memory: `user`/`project`/`local`スコープ

### Agent Teams（実験的）
- 有効化: `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`（settings.jsonまたは環境変数）
- リード1名 + チームメイト複数名の構成
- 共有タスクリスト + メッセージングシステム
- 最適構成: 3-5名（1名あたり5-6タスク目安）
- 強いユースケース:
  - 複数側面の同時調査・レビュー
  - 新モジュール/機能の分担実装
  - 競合仮説の並列テスト
  - フロントエンド/バックエンド/テストの横断調整

### Worktree Isolation
- `claude --worktree`またはサブエージェントで`isolation: "worktree"`
- git worktreeで隔離された作業コピーを自動作成
- **sparsePaths**: `worktree.sparsePaths`で必要ディレクトリのみチェックアウト（モノレポ向け）
- **WorktreeCreate/WorktreeRemove hooks**: デフォルトgit動作を置換可能（SVN, Perforce, Mercurial対応）
- セッション終了時:
  - 変更なし → worktreeとブランチ自動削除
  - 変更あり → keep（保持）またはremove（削除）を選択

### コミュニティのマルチエージェントツール
- **Gas Town（Steve Yegge）**: AI向けKubernetesのようなエージェントIDE
- **Multiclaude**: Brownian ratchet哲学のマルチエージェントオーケストレーター（CIパス→即マージ）
- **ruflo**: Claudeネイティブのスウォームオーケストレーションプラットフォーム
- **claude-code-mcp**: Claude CodeをMCPサーバーとして公開

---

## 4. MCP（Model Context Protocol）最新動向

### MCP Elicitation（v2.1.76）
- MCPサーバーがタスク中にフォーム/ブラウザURLで構造化入力を要求
- `Elicitation`/`ElicitationResult`フックで応答制御

### Tool Search（遅延ロード）
- コンテキスト使用量を最大95%削減
- v2.1.76でコンパクション後のスキーマ消失バグ修正済み

### エコシステム規模
- 2026年2月時点で200+のMCPサーバーが存在
- GitHub MCPサーバーが最も人気（92%のMCPユーザーが最初に有効化）
- SDK: `@modelcontextprotocol/sdk` v1.12

### claude.ai MCP connectors
- v2.1.46+でClaude Code内からclaude.aiのMCPコネクタを利用可能

### OAuth対応
- MCP OAuth step-up auth + discovery caching
- トークン自動リフレッシュ（v2.1.76で再接続バグ修正）

### 注目MCPサーバー
| サーバー | 用途 |
|---------|------|
| @modelcontextprotocol/server-github | Issues, PRs, ファイル, 検索（15ツール） |
| Playwright MCP | E2Eテスト, Webスクレイピング（アクセシビリティツリー） |
| claude-code-mcp (steipete) | Claude Code自体をMCPサーバーとして公開 |
| zilliztech/claude-context | コード検索MCP（コードベース全体をコンテキスト化） |

---

## 5. CLAUDE.md・プロンプトのベストプラクティス

### CLAUDE.md最適化
- **200行以内**: フロンティアモデルは約150-200指示に従える。システムプロンプトで50消費→ユーザー指示は100-150が限度
- **`/init`で初期生成**: コードベース分析でビルドシステム・テスト・コードパターン検出
- **@インポート構文**: `@docs/git-instructions.md`で外部ファイル参照
- **配置の階層**: `~/.claude/CLAUDE.md`(全セッション) → `./CLAUDE.md`(プロジェクト) → 子ディレクトリ(オンデマンド)

### 効果的なプロンプトパターン
1. **検証手段を提供する**: テスト・スクリーンショット・期待出力を含める（最高レバレッジ）
2. **4フェーズワークフロー**: Explore → Plan → Implement → Commit
3. **インタビュー方式**: 大きな機能は`AskUserQuestion`ツールで深掘り→spec.md→新セッションで実装
4. **スコープ指定**: 曖昧な「バグ修正」ではなく症状・調査対象を具体的に記述

### コンテキスト管理の黄金ルール
- **2回修正しても直らない** → `/clear`してより良いプロンプトで再開
- **30分スプリント**: 機能/修正ごとに区切り、間に`/compact`実行 → 4時間で85%性能維持
- **コンパクション閾値**: 85%に設定すると95%より平均2.3秒レスポンス改善

### 新スラッシュコマンド完全一覧
| コマンド | 機能 |
|---------|------|
| `/loop` | 定期的にプロンプト/コマンドを繰り返し実行 |
| `/effort` | effortレベル設定（low ○ / medium ◐ / high ●） |
| `/context` | コンテキスト負荷の最適化提案を表示 |
| `/color` | セッションカラーカスタマイズ |
| `/plan <desc>` | 説明付きでplan mode即開始 |
| `/voice` | 音声入力モード（push-to-talk, 20言語） |
| `/btw` | コンテキストに残らないサイドクエスチョン |
| `/compact <inst>` | 指示付きコンパクション |
| `/rewind` | チェックポイントに戻る |
| `/rename` | セッション名設定 |
| `/cost` | トークン消費量確認 |
| `/remind` | メモリ再読み込み |

---

## 6. GitHub Actions + Claude Code

### 公式アクション: anthropics/claude-code-action@v1
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

### 注意点
- Claude CodeがPR作成後の後続コミットは`GitHub Actions Bot`名で実行 → CI非トリガー
- PAT（Personal Access Token）使用でCIトリガーを有効化可能

### 自動化パターン
- `@claude`メンションでPR/Issue対応
- Issue → PR自動生成
- スケジュールメンテナンス（リポジトリヘルスチェック）
- Issue自動トリアージ・ラベリング
- セキュリティフォーカスレビュー
- リリースノート自動生成

---

## 7. headlessモード（claude -p）

```bash
# 基本
claude -p "Explain what this project does"

# セッション名指定（v2.1.76 -n/--name）
claude -p "Review code" -n "code-review-session"

# 構造化出力
claude -p "List all API endpoints" --output-format json

# JSONスキーマ付き
claude -p "Extract function names" --output-format json \
  --json-schema '{"type":"object","properties":{"functions":{"type":"array","items":{"type":"string"}}}}'

# ストリーミング
claude -p "Analyze log" --output-format stream-json --verbose

# 会話継続
session_id=$(claude -p "Start review" --output-format json | jq -r '.session_id')
claude -p "Continue review" --resume "$session_id"

# ファンアウト（大規模マイグレーション）
for file in $(cat files.txt); do
  claude -p "Migrate $file" --allowedTools "Edit,Bash(git commit *)"
done
```

---

## 8. Claude Agent SDK

- Claude Code SDKが**Agent SDK**にリネーム（deep researchがファーストクラスユースケースに）
- platform.claude.com/docs/en/agent-sdk/overview で公式ドキュメント
- スラッシュコマンドもSDK内で定義可能

---

## 9. コミュニティ動向・統計

### GitHubコミット統計
- 2026年2月時点: 公開GitHubコミットの**4%**がClaude Codeによるもの
- 2026年末までに**20%超**の予測（GIGAZINE報道）

### コミュニティリソース
- [awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code): Skills, hooks, slash-commands, agent orchestrators一覧
- [claude-code-best-practice](https://github.com/shanraisshan/claude-code-best-practice): CLAUDE.mdベストプラクティス集
- [claude-code-hooks-mastery](https://github.com/disler/claude-code-hooks-mastery): hooks実践ガイド
- [claude-code-system-prompts](https://github.com/Piebald-AI/claude-code-system-prompts): システムプロンプト全公開

### Zenn（日本語コミュニティ）
- [Claude Code GitHub Actions設定Tips](https://zenn.dev/tomodo_ysys/articles/claude-code-github-actions-tips)
- [Claude Codeを使いこなす10のTips【2026年版】](https://zenn.dev/seeda_yuto/articles/claude-code-tips-2026)
- [Claude Codeで開発を10倍速にする完全ガイド](https://zenn.dev/riche/articles/claude-code-dev-guide-2026)

### Anthropic公式
- Claude Partner Network発表: 初期$1億のパートナー支援プログラム
- Automated Alignment Agent (A3): LLMの安全性障害を自動緩和するフレームワーク
- AuditBench: 56モデルの隠れた行動を評価するベンチマーク

---

## 10. よくある失敗パターンと対策

| パターン | 対策 |
|---------|------|
| Kitchen Sink Session | タスク間で`/clear` |
| 繰り返し修正 | 2回失敗→`/clear`+より良いプロンプト |
| CLAUDE.md肥大化 | 200行以内に剪定。Skills/子ディレクトリに分離 |
| Trust-then-Verify Gap | 必ず検証手段提供（テスト・スクリプト） |
| Infinite Exploration | スコープ限定 or サブエージェント使用 |
| コンパクション情報損失 | PostCompactフック(v2.1.76)で重要情報を再注入 |

---

## 11. TASプロジェクト構成改善提案

### 現状の課題
1. **プロジェクトルートに`.claude/`ディレクトリがない** — `claude-config/`に設定が分散
2. **CLAUDE.md**が`claude-config/CLAUDE.md`にありClaude Codeが自動読み込みしない
3. **Skills/Hooks/Agents**が未設定
4. **PostCompactフック**なし → コンパクション時にLark Base ID等の重要情報が失われるリスク

### 推奨アクション

#### 即座に実行可能（優先度: 高）

**A. PostCompactフック導入**
```json
// .claude/settings.json
{
  "hooks": {
    "PostCompact": [{
      "hooks": [{
        "type": "prompt",
        "prompt": "コンパクション後の確認: Lark CRM Base ID(BodWbgw6DaHP8FspBTYjT8qSpOe), タスクテーブル(tblGrFhJrAyYYWbV), 商談テーブル(tbl1rM86nAw9l3bP)が記憶に残っているか確認し、失われていれば再記憶してください"
      }]
    }]
  }
}
```

**B. `/effort`コマンドの活用**
- 日常タスク: medium（デフォルト）
- 重要な設計・デバッグ: `ultrathink`キーワードまたは`/effort high`

**C. `/context`コマンドで定期チェック**
- セッション中にコンテキスト状態を確認し、不要なSkillsを除外

#### 中期（Mac mini購入後）

**D. Agent Teams有効化**
- `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`
- CRM更新+コンテンツ生成+テストを並列実行

**E. カスタムMCPサーバー構築**
- Lark Base直接操作用MCPサーバー（50行以下で実装可能）
- freee API連携MCPサーバー

**F. `/loop`でモニタリング自動化**
- CRMヘルスチェック、GitHub Actionsステータス監視を`/loop`で定期実行

---

## 更新履歴
| 日付 | 内容 |
|------|------|
| 2026-03-16 | v2.1.76対応。フック3タイプ+HTTP詳細追加、PostCompactフック、worktree sparsePaths、Agent SDK改名、コミュニティ統計更新 |
| 2026-03-15 | 初版作成。v2.1.76時点の包括的レポート |

---

## Sources
- [Claude Code Changelog](https://code.claude.com/docs/en/changelog)
- [Claude Code Hooks Reference](https://code.claude.com/docs/en/hooks)
- [Claude Code Slash Commands](https://code.claude.com/docs/en/slash-commands)
- [Claude Code Agent Teams](https://code.claude.com/docs/en/agent-teams)
- [Claude Code MCP](https://code.claude.com/docs/en/mcp)
- [Claude Code Common Workflows](https://code.claude.com/docs/en/common-workflows)
- [Claude Code GitHub Actions](https://code.claude.com/docs/en/github-actions)
- [Claude Agent SDK](https://platform.claude.com/docs/en/agent-sdk/overview)
- [Claude Code March 2026 Updates](https://pasqualepillitteri.it/en/news/381/claude-code-march-2026-updates)
- [Claude Code Hooks Guide 2026 - Pixelmojo](https://www.pixelmojo.io/blogs/claude-code-hooks-production-quality-ci-cd-patterns)
- [Claude Code Hooks - 20+ Examples](https://dev.to/lukaszfryc/claude-code-hooks-complete-guide-with-20-ready-to-use-examples-2026-dcg)
- [Best Claude Code MCP Servers](https://www.turbodocx.com/blog/best-claude-code-skills-plugins-mcp-servers)
- [Claude Code Worktree Guide](https://claudefa.st/blog/guide/development/worktree-guide)
- [awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code)
- [claude-code-best-practice](https://github.com/shanraisshan/claude-code-best-practice)
- [Claude Code GitHub Commits 4%](https://gigazine.net/gsc_news/en/20260210-claude-code-github-commits-4-percent-20-percent/)
- [Anthropic Engineering Blog](https://www.anthropic.com/engineering)
- [Releasebot - Claude Code](https://releasebot.io/updates/anthropic/claude-code)
- [Zenn - Claude Code Tips 2026](https://zenn.dev/seeda_yuto/articles/claude-code-tips-2026)
- [Zenn - Claude Code Dev Guide 2026](https://zenn.dev/riche/articles/claude-code-dev-guide-2026)
- [Zenn - GitHub Actions Tips](https://zenn.dev/tomodo_ysys/articles/claude-code-github-actions-tips)
