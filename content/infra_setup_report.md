# インフラ整備レポート

作成日: 2026-03-17 / 実行者: Claude Code (自律モード)

---

## 1. Claude Code Skills (5件作成)

場所: `/mnt/c/Users/USER/.claude/skills/`

| ファイル | 用途 |
|---------|------|
| crm-check.md | CRM健全性チェック（商談ステージ未設定・重複取引先・放置商談の検出） |
| seo-audit.md | SEO監査（GA4分析・メタ情報チェック・Bing/Google流入分析） |
| article-review.md | 記事品質レビュー（SEO・コンテンツ・技術正確性・社外秘チェック） |
| weekly-kpi.md | 週次KPIレポート生成（CRM・GA4・GitHub Actions集計） |
| gmail-draft.md | Gmail下書き作成（HTML形式必須・社外秘チェック・署名テンプレート） |

### 使用方法
Claude Code内で `/skills` コマンドでスキル一覧を確認し、スキル名を指定して呼び出す。

---

## 2. Hooks設定 (2種類)

### 2-1. PreToolUse: シークレット漏洩検知 (新規)

場所: `/mnt/c/Users/USER/.claude/hooks/check_secrets.sh`
設定: `/mnt/c/Users/USER/.claude/settings.json` の hooks.PreToolUse

**検知対象:**
- `automation_config.json` への Write/Edit/git操作 -> ブロック
- `.env` / `.env.local` / `.env.production` への書き込み -> ブロック
- APIキーパターン: `sk-ant-*`, `sk-*`(40字以上), `AKIA*`, `cli_*`, 秘密鍵, GitHub PAT
- `git add/commit automation_config` -> ブロック

**テスト結果:**
- 正常操作通過: PASS
- automation_config.jsonブロック: PASS
- APIキー検知: PASS
- cli_パターン検知: PASS
- .envブロック: PASS
- Read操作スルー: PASS

### 2-2. PostCompact: コンパクション後の重要情報保持確認 (新規)

設定: `/mnt/c/Users/USER/.claude/settings.json` の hooks.PostCompact

コンパクション実行後に以下の情報がコンテキストに残っているか自動確認:
- Lark CRM Base App Token
- 主要テーブルID（商談・タスク管理・取引先・受注台帳）
- automation_config.json gitコミット禁止ルール
- 社外秘出力禁止ルール

### 既存hooks (変更なし)

場所: `/home/user/.claude/hooks/` + `/home/user/.claude/settings.json`

| フック | スクリプト | 機能 |
|--------|----------|------|
| SessionStart | session-init.sh | セッション初期化 |
| PreToolUse | pre-commit-check.sh | git操作のセキュリティチェック |
| PostToolUse | memory-check.sh | メモリ自動保存チェック |
| PostCompact | post-compact.sh | コンパクション後処理 |
| Stop | memory-stop-check.sh + notify-chime.sh | セッション終了時処理 |

**注意**: 既存hooks (home) と 新規hooks (project) は併存する。PreToolUseは両方実行される（home: git操作チェック、project: シークレット検知）。

---

## 3. 専門エージェント定義 (4件作成)

場所: `/mnt/c/Users/USER/.claude/agents/`

| ファイル | 役割 | 主な知識 |
|---------|------|---------|
| crm-agent.md | CRM管理 | Lark Base 7テーブル構造・商談フロー・営業チーム情報 |
| seo-agent.md | SEO/Web分析 | tokaiair.com構成・GA4/IndexNow・Bing最適化 |
| content-agent.md | コンテンツ作成 | ドローン測量専門用語・CTA設計・E-E-A-T |
| infra-agent.md | インフラ/DevOps | GitHub Actions 14ワークフロー・Cloudflare・NAS |

### 各エージェントの共通制約
- 社外秘情報の外部出力禁止
- データ変更前スナップショット必須
- WordPress変更は wp_safe_deploy.py 経由

### 使用方法
`/agent crm-agent` のように呼び出す。独立コンテキストウィンドウで実行される。

---

## ディレクトリ構成 (最終)

```
/mnt/c/Users/USER/.claude/
  settings.json          # hooks設定（PreToolUse + PostCompact）
  settings.local.json    # ローカル権限設定（既存）
  skills/
    crm-check.md
    seo-audit.md
    article-review.md
    weekly-kpi.md
    gmail-draft.md
  agents/
    crm-agent.md
    seo-agent.md
    content-agent.md
    infra-agent.md
  hooks/
    check_secrets.sh     # シークレット漏洩検知

/home/user/.claude/
  settings.json          # グローバルhooks設定（既存・変更なし）
  hooks/
    session-init.sh      # 既存
    pre-commit-check.sh  # 既存
    memory-check.sh      # 既存
    post-compact.sh      # 既存
    memory-stop-check.sh # 既存
    notify-chime.sh      # 既存
```

---

## 設計判断メモ

1. **スキルは5つに絞った**: 頻出操作のみ。過剰なスキルはコンテキスト負荷になる
2. **hookは2種類に限定**: 既存hooks（home）と重複しないよう、ファイル書き込み時のシークレット検知とPostCompactに特化
3. **エージェントは4職能**: CRM/SEO/コンテンツ/インフラ。営業エージェントは商談操作がCRMエージェントと重複するため省略
4. **PostCompactプロンプトは英語**: 日本語だとUTF-16LE問題が発生するリスクがあるため英語で記述
