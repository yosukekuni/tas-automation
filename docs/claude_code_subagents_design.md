# Claude Code Subagents設計

作成日: 2026-03-14 / ステータス: 凍結（設計書のみ）

## 概要

`.claude/agents/` に専門エージェント定義ファイルを配置し、`/agent` コマンドで呼び出す。各エージェントは専門知識・権限・使用ツールを持つ。

## エージェント一覧

### 1. crm-agent.md — CRM管理エージェント

**専門知識:**
- Lark CRM Base構造（6テーブル + タスク管理Base）
- 商談ステージフロー、受注/失注判定ロジック
- 顧客セグメント分類（A/B/C/D）

**権限:**
- Lark Base API（読み書き）
- CRM関連スクリプト実行（crm_monitor, crm_dedup, crm_segment_classifier等）
- メール送信（review_agent経由チェック必須）

**使用ツール:** Lark Base API, Gmail API

**プロンプト骨子:**
```markdown
あなたはCRM管理の専門エージェントです。
- CRM Base ID: BodWbgw6DaHP8FspBTYjT8qSpOe
- 商談テーブル: tbl1rM86nAw9l3bP
- 社外秘情報（顧客名・営業成績）は絶対に外部出力しない
- メール送信前は必ずreview_agent emailチェックを実行
```

### 2. seo-agent.md — SEO/コンテンツエージェント

**専門知識:**
- tokaiair.com サイト構造、記事44本+15本の管理
- Bing 68.6%/Google 11.5%の流入特性
- WordPress操作（wp_safe_deploy.py経由必須）

**権限:**
- WordPress API（wp_safe_deploy.py経由のみ）
- GA4/Search Console データ参照
- IndexNow API

**使用ツール:** WordPress REST API, GA4 API, Search Console API

### 3. content-agent.md — コンテンツ作成エージェント

**専門知識:**
- ドローン測量・土量計算の専門用語
- 記事構成テンプレート、CTA設計
- 社外秘ルール（顧客依存率・営業成績・ランウェイ・顧客名は絶対に出さない）

**権限:**
- 記事HTML生成（review_agent articleチェック必須）
- 画像選定指示
- WordPress下書き作成（wp_safe_deploy.py経由）

**使用ツール:** WordPress REST API, review_agent

## エージェント間連携

```
ユーザー指示
  ├→ crm-agent: 顧客データ取得・分析
  ├→ seo-agent: 検索順位・流入分析
  └→ content-agent: 記事作成・更新
       ↓
  review_agent: 品質チェック（全エージェント共通ゲート）
```

- エージェント間のデータ受け渡しはファイル（JSON/CSV）経由
- 全エージェントに共通制約: review_agentチェック必須、社外秘ルール遵守

## 工数見積もり

| 作業 | 工数 |
|------|------|
| crm-agent.md作成 | 2時間 |
| seo-agent.md作成 | 2時間 |
| content-agent.md作成 | 2時間 |
| 連携テスト | 2時間 |
| **合計** | **8時間** |

## 優先順位

**中〜低**: 現状は単一セッションで十分回っている。タスク量が増えてボトルネックになったら実装。
