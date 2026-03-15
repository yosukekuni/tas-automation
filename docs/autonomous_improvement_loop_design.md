# 自律改善ループ設計

作成日: 2026-03-14 / ステータス: 凍結（設計書のみ）

## 概要

Claude Code（実装）→ review_agent（レビュー）→ Claude Code（修正）の自動サイクルを構築し、人間の承認なしに品質保証された成果物を生成する。

## 現状

- review_agent.py は既に稼働中（article / email / css / deploy モード）
- 各スクリプトにreview_agentチェックが組み込み済み
- ただし現在は「チェック→問題報告→手動修正」のフロー

## 自律ループフロー

```
Claude Code: 成果物作成（記事HTML / CSS / メール文面）
  ↓
review_agent.py: 自動チェック
  ↓ JSON結果を解析
  ├→ PASS: デプロイ実行（wp_safe_deploy.py / git push等）
  └→ FAIL: 修正指示を解析
        ↓
      Claude Code: 指摘事項を自動修正
        ↓
      review_agent.py: 再チェック（最大3ループ）
        ↓ 3回FAIL → 人間にエスカレーション（Lark通知）
```

### 品質保証フロー: 記事作成

```bash
# auto_article_pipeline.sh
python3 content_generator.py --topic "$1" --output /tmp/article.html
for i in 1 2 3; do
  result=$(python3 review_agent.py article /tmp/article.html --json)
  if echo "$result" | jq -e '.pass == true'; then
    python3 wp_safe_deploy.py --file /tmp/article.html
    exit 0
  fi
  # review_agentの指摘をClaude Codeに渡して修正
  python3 content_fixer.py --article /tmp/article.html --feedback "$result"
done
# 3回失敗 → エスカレーション
python3 lark_notify.py "記事自動修正が3回失敗。手動確認が必要です。"
```

### 品質保証フロー: CSS変更

```bash
# CSSスニペット変更時
# 1. review_agent css でチェック（inherit!important禁止等）
# 2. PASS → wp_safe_deploy.py でデプロイ
# 3. LiteSpeedキャッシュパージ依頼通知
```

## review_agentチェック項目（既存）

| モード | チェック内容 |
|--------|-------------|
| article | 社外秘漏洩、HTMLバリデーション、SEOメタ、内部リンク |
| email | 宛先・敬称、添付忘れ、社外秘、トーン |
| css | inherit!important禁止、セレクタ競合、レスポンシブ |
| deploy | git diff確認、設定ファイル混入、テスト実行 |

## エスカレーション条件

- 3回連続FAIL
- review_agentが「CRITICAL」判定を出した場合
- 社外秘漏洩の疑いがある場合（即時ブロック、ループ不可）

## 工数見積もり

| 作業 | 工数 |
|------|------|
| ループ制御スクリプト | 3時間 |
| content_fixer.py（修正指示→自動修正） | 4時間 |
| エスカレーション通知 | 1時間 |
| テスト（各モード） | 2時間 |
| **合計** | **10時間** |

## 優先順位

**中**: review_agent自体は稼働中なのでループ化の追加工数は限定的。コンテンツ量産フェーズで効果を発揮する。売上直結タスク優先のため、現時点では凍結。
