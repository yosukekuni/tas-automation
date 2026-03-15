# t-as.netドメイン活用検討

作成日: 2026-03-14 / ステータス: 凍結（設計書のみ）

## 概要

t-as.netドメインの現状確認と活用方針を検討する。

## 現状の利用状況

- 既存の `domain_utilization_plan.md` で4案の比較分析を実施済み
- 結論: **案4（301リダイレクト）→ 案3（短縮URL）→ 案1（広告LP）** の段階的活用を推奨済み

## tokaiair.comとの使い分け

| ドメイン | 用途 | 役割 |
|---------|------|------|
| tokaiair.com | メインサイト | SEO資産集約、全コンテンツのハブ |
| t-as.net（推定） | 補助ドメイン | 短縮URL / リダイレクト先 |
| tomoshi.jp | TOMOSHI事業部 | AI活用コンサルティング専用 |

## 推奨方針（domain_utilization_plan.mdと整合）

### 即時: 301リダイレクト

- t-as.net → tokaiair.com に301リダイレクト設定
- 工数: 5分（DNS設定のみ）
- 目的: ドメイン放置によるスパム悪用防止

### 短期: 営業用短縮URL

- Cloudflare Workers（無料枠）でパスベースリダイレクト
- 例:
  - `t-as.net/drone` → `tokaiair.com/drone-survey/`
  - `t-as.net/quote` → `tokaiair.com/contact/`
  - `t-as.net/case/xxx` → 各事例ページ
- 名刺・提案書・メール署名で使用
- クリック計測で営業効果を可視化（新美・政木のどの資料が参照されているか）

### 中期: 広告LP（広告予算確保後）

- 広告出稿時のランディングページを別ドメインに設置
- SEOドメイン（tokaiair.com）と広告LPの分離
- Cloudflare Pages（無料枠）で静的HTML

## 非推奨

- **マイクロサイト分割は絶対に避ける**
  - Bing 68.6%の流入構成でドメインパワー分散は致命的
  - 44本+15本の記事資産はtokaiair.comに集約維持

## 工数見積もり

| 作業 | 工数 |
|------|------|
| 301リダイレクト設定 | 5分 |
| 短縮URL（Cloudflare Workers） | 2〜3時間 |
| 広告LP構築（将来） | 1〜2日 |

## 優先順位

**最低**: 301リダイレクト設定のみ5分で実施可能。それ以外は売上安定後。既にdomain_utilization_plan.mdで詳細分析済みのため、本設計書は参照用サマリー。
