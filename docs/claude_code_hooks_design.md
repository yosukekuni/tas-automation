# Claude Code Hooks設計

作成日: 2026-03-14 / ステータス: 凍結（設計書のみ）

## 概要

`.claude/hooks/` にフックスクリプトを配置し、コミット・プッシュ時のセキュリティチェックとレビュー自動化を実現する。

## フック一覧

### 1. pre-commit: シークレット漏洩検知

```json
// .claude/hooks.json
{
  "hooks": {
    "pre-commit": [
      {
        "command": ".claude/hooks/check_secrets.sh",
        "description": "API key・パスワード・automation_config.json混入防止"
      }
    ],
    "post-push": [
      {
        "command": ".claude/hooks/trigger_review.sh",
        "description": "review_agent自動トリガー"
      }
    ]
  }
}
```

**check_secrets.sh の検知対象:**
- `automation_config.json` のステージング検知 → 即ブロック
- APIキーパターン: `sk-`, `cli_`, `Bearer`, `token` 等の正規表現マッチ
- パスワード・認証情報: `.env`, `credentials.json`, `*_secret*`
- Lark App Secret, Claude API Key, GA4サービスアカウントキー

**実装方針:**
```bash
#!/bin/bash
# .claude/hooks/check_secrets.sh
BLOCKED_FILES="automation_config.json|\.env|credentials\.json|service_account.*\.json"
SECRET_PATTERNS="sk-[a-zA-Z0-9]{20,}|cli_[a-f0-9]{16,}|AKIA[0-9A-Z]{16}"

# ステージングされたファイル名チェック
git diff --cached --name-only | grep -E "$BLOCKED_FILES" && exit 1

# ファイル内容のシークレットパターンチェック
git diff --cached -U0 | grep -E "$SECRET_PATTERNS" && exit 1

exit 0
```

### 2. post-push: review_agent自動トリガー

**trigger_review.sh:**
- プッシュされた差分ファイルを取得
- `.py`, `.html`, `.css` ファイルに対して `review_agent.py` を実行
- 結果をLark通知（既存のcrm_notifications基盤を使用）

## 設定方法

1. `.claude/hooks/` ディレクトリ作成
2. 各スクリプトに実行権限付与 (`chmod +x`)
3. `hooks.json` を `.claude/` に配置
4. Claude Codeがフック設定を自動認識

## 工数見積もり

| 作業 | 工数 |
|------|------|
| check_secrets.sh作成・テスト | 1時間 |
| trigger_review.sh作成 | 1時間 |
| hooks.json設定 | 15分 |
| **合計** | **2.5時間** |

## 優先順位

**中**: automation_config.jsonの誤コミットリスクは実在するが、現在は手動確認で対応中。余裕ができたら実装。
