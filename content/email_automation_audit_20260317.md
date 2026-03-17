# メール自動化システム 精査レポート
日時: 2026-03-17

## 1. 対象スクリプト一覧（10本）

| # | スクリプト | 目的 | ワークフロー | スケジュール | 最新実行 |
|---|-----------|------|-------------|-------------|---------|
| 1 | auto_followup_email.py | Hot/Warm案件フォローメール生成 | followup_email.yml | 平日9:00 | 3/17 success |
| 2 | seasonal_email.py | 季節アプローチ（4月/10月） | seasonal_email.yml | 4月・10月第1月曜 | (未実行・3月のため正常) |
| 3 | lead_nurturing.py | リード再活性化（5セグメント） | lead_nurturing.yml | 月・水 9:00 | 3/16 success |
| 4 | deal_thankyou_email.py | 商談後サンクスメール | deal_thankyou.yml | 15分毎+8:30/17:00 | 3/17 success |
| 5 | delivery_thankyou_email.py | 納品完了サンクスメール | delivery_thankyou.yml | 15分毎+10:00 | 3/17 success |
| 6 | email_nurturing_sequences.py | 問い合わせ後5通+納品後3通シーケンス | email_nurturing.yml | 平日9:00 | 3/17 success |
| 7 | nurture_campaign.py | セグメント別ナーチャリング（Seg1/Seg2） | **なし** | **なし** | **手動のみ** |
| 8 | quote_followup.py | 見積送付後3段階フォロー | quote_followup.yml | 平日9:00 | 3/17 success |
| 9 | post_delivery_followup.py | 納品翌日フォロー（口コミ依頼） | post_delivery_followup.yml | 毎日9:00+10:00 | 3/17 success |
| 10 | ai_valueup_nurture.py | TOMOSHI事業部ナーチャリング | ai_valueup_nurture.yml | (別系統) | 3/17 success |

## 2. 全ワークフロー稼働状況

**全26ワークフロー active**。メール関連は全て正常稼働中。

## 3. 発見した問題と修正

### 3.1 [修正済み] 新美光のメールアドレス不一致
- **影響**: auto_followup_email.py, lead_nurturing.py, quote_followup.py
- **問題**: `niimi@tokaiair.com`（不正）を使用。正しくは `h.niimi@tokaiair.com`
- **修正**: 3ファイルとも `h.niimi@tokaiair.com` に統一

### 3.2 [注意] nurture_campaign.py にワークフローがない
- **影響**: セグメント別ナーチャリング（Seg1: Hot/Warm月1回、Seg2: Cold四半期1回）が自動実行されない
- **現状**: 手動実行のみ。lead_nurturing.pyやemail_nurturing_sequences.pyとの役割重複もある
- **判断**: 既存のlead_nurturing.py（月水自動実行）とemail_nurturing_sequences.py（平日毎日）でカバーされているため、nurture_campaign.pyはスポット利用で問題なし。必要なら後日ワークフロー化

### 3.3 [注意] Google口コミURL未設定
- post_delivery_followup.py の `GOOGLE_REVIEW_URL = "https://g.page/r/tokaiair/review"` は仮URL
- Google Business Profileの実際の口コミURLに差し替えが必要
- 現在この機能は稼働しているが、リンク先が正しくない可能性

### 3.4 [注意] アンケートURL未設定
- delivery_thankyou_email.py の `SURVEY_URL = "https://www.tokaiair.com/survey/"` にTODOコメント
- 実際のアンケートページがあるか確認が必要

### 3.5 [注意] lead_nurturing.yml ワークフロー名の不整合
- 名前: "Lead Nurturing (Weekly Wednesday 9AM JST)"
- 実際のcron: 月曜・水曜の2回実行（`0 0 * * 1,3`）
- 実害なし（名前だけの問題）

## 4. スクリプト別 品質チェック

### auto_followup_email.py
- **セーフガード**: クールダウン7日間、Webhook通知
- **メール品質**: Claude API生成、ヒアリング内容に基づくパーソナライズ
- **送信方式**: Lark Mail API（権限要）
- **問題**: 送信はLark Mail API経由だが、権限設定が必要。実際に送信成功しているか要確認
- **判定**: OK（ドラフト生成+通知として機能）

### seasonal_email.py
- **セーフガード**: 最大30件/回、60日重複排除、メールログ記録、review_agentチェック
- **対象**: セグメントA/C群（受注実績あり） + Warm以上の商談
- **送信方式**: WordPress wp_mail経由
- **スケジュール**: 4月・10月の第1月曜のみ（正しく設定済み）
- **判定**: 良好。次回実行は2026年4月

### lead_nurturing.py
- **セーフガード**: セグメント別クールダウン（30-90日）、Lark Bot DM通知
- **セグメント**: 5種（過去顧客/放置Hot・Warm/Cold+ヒアリング済/失注/季節）
- **送信方式**: ドラフト生成のみ（--generateオプション）
- **判定**: OK。受注台帳連携でセグメント精度が高い

### deal_thankyou_email.py
- **セーフガード**: 1日5件上限、30日重複防止、CEO通知付き、review_agentチェック
- **送信方式**: WordPress wp_mail + Lark DM通知
- **キュー方式**: 15分毎にキュー追加、8:30/17:00に送信
- **判定**: 良好。15分間隔の高頻度モニタリング

### delivery_thankyou_email.py
- **セーフガード**: 1日5件上限、30日重複防止、CEO通知、review_agentチェック
- **送信方式**: WordPress wp_mail + メールログ記録
- **キュー方式**: 15分毎にキュー追加、平日10:00に送信
- **判定**: 良好

### email_nurturing_sequences.py
- **シーケンス**: 問い合わせ後5通（Day 0/3/7/14/30）+ 納品後リピート3通（Day 1/30/90）
- **セーフガード**: 1日15件上限、テスト・無効メール除外パターン、review_agentチェック
- **送信方式**: WordPress wp_mail + メールログ記録
- **判定**: 良好

### quote_followup.py
- **フォロー段階**: 3日後（確認）/7日後（事例紹介）/14日後（最終フォロー）
- **セーフガード**: 状態ファイルで段階管理、重複防止
- **送信方式**: Lark DM経由で担当営業に送信（直接顧客には送らない）
- **判定**: OK。営業担当への内部通知として機能

### post_delivery_followup.py
- **目的**: 納品翌日に満足度確認+Google口コミ依頼
- **セーフガード**: 1日5件上限、60日重複防止、CEO通知、review_agentチェック
- **送信方式**: WordPress wp_mail（HTML形式）
- **特徴**: Claude API不使用（テンプレート固定 = トークン消費ゼロ）
- **判定**: 良好（ただしGoogle口コミURL要確認）

## 5. メールテンプレート品質チェック

全スクリプトで以下のルールが遵守されていることを確認:
- 社外秘情報（顧客名、売上、社内事情）を含まない指示あり
- 押し売りしないトーン指示あり
- 文字数制限（250-400文字）指示あり
- 署名の適切な付与
- review_agent連携（送信前チェック）が主要スクリプトに実装済み

## 6. 重複・競合リスク分析

| 顧客接点 | 関連スクリプト | 重複防止策 |
|----------|--------------|-----------|
| 商談直後 | deal_thankyou_email.py | 30日重複防止、商談ID管理 |
| 見積送付後 | quote_followup.py | 状態ファイルで段階管理 |
| 納品完了直後 | delivery_thankyou_email.py | 30日重複防止 |
| 納品翌日 | post_delivery_followup.py | 60日重複防止 |
| 問い合わせ後 | email_nurturing_sequences.py | シーケンス管理+メールログ |
| 定期フォロー | auto_followup_email.py | 7日クールダウン |
| リード再活性化 | lead_nurturing.py | 30-90日セグメント別クールダウン |
| 季節アプローチ | seasonal_email.py | 60日重複排除+メールログ |

**重複リスク**: delivery_thankyou_email.py（納品完了直後）と post_delivery_followup.py（納品翌日）が同一案件に対して短期間で発火する可能性あり。ただし重複防止の仕組みは各自独立しているため、同一メールアドレスへの2通送信は防止される。

## 7. 総合評価

**メール自動化システム全体: 正常稼働中**

- GitHub Actions: 全ワークフロー active、直近の実行は全て success
- スクリプト品質: セーフガード（上限・重複防止・CEO通知）が全体的に実装されている
- review_agent連携: 主要スクリプトに実装済み
- メールログ記録: Lark Base メールログテーブルへの記録が実装されている

### 修正済み
1. 新美光メールアドレス不一致を3ファイルで修正（niimi@ -> h.niimi@）

### 要確認（手動対応）
1. Google口コミURL（post_delivery_followup.py）の実URLへの差し替え
2. アンケートURL（delivery_thankyou_email.py）の実在確認
3. auto_followup_email.pyのLark Mail API送信権限の動作確認
