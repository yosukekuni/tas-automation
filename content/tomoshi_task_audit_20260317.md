# TOMOSHI事業部 残タスク精査・消化レポート

**作成日:** 2026-03-17
**対象:** TOMOSHI事業部の残タスクの棚卸し・品質改善

---

## 1. タスク一覧と現状ステータス

| # | タスク | ステータス | 備考 |
|---|--------|-----------|------|
| 1 | 加藤TL経由で日程調整 | **ユーザー操作待ち** | 変更なし。加藤TLからの連絡待ち |
| 2 | 加藤TL経由の紹介（提案書・面談台本） | **待機中→準備完了** | 本セッションで品質改善・リサーチ完了 |
| 3 | TOMOSHI CTA改善 | **前セッションで完了** | 段階的CTA構造に変更済み |
| 4 | TOMOSHI戦略レビュー | **前セッションで完了** | strategy_review.md作成済み |

---

## 2. 本セッションで実施した改善

### 2-1. 提案書の品質改善 (`proposal_kaitori_center.md`)

| 修正項目 | Before | After |
|---------|--------|-------|
| セクション3タイトル | 「Claude Code による業務自動化」 | 「AI業務自動化による仕組み化」 |
| 技術名の露出 | Claude Code、GitHub Actions、API等を明記 | すべて「仕組み」「自動化」に統一 |
| 原価の露出 | 「月額コスト約5,000円」「サーバー代ゼロ」 | 「低コストで運用可能」「専任エンジニア不要」 |
| 自動化の一覧 | 6項目のみ（「12の自動化」と不整合） | 12項目すべてを記載 |
| 連絡先 | yosuke.toyoda@gmail.com / tokaiair.comのみ | info@tomoshi.jp / tomoshi.jp追記 |
| 会社情報 | tokaiair.comのみ | TOMOSHI事業も明記、tomoshi.jp追加 |
| PEファンド比較 | 「月5,000円〜」「競合ゼロ」 | 「圧倒的に低コスト」「ほぼゼロ」 |

### 2-2. 面談台本の品質改善 (`meeting_script_kaitori_center.md`)

| 修正項目 | Before | After |
|---------|--------|-------|
| 維持費の回答 | 「月数千円のサーバー代程度」 | 「非常に低い」「一般的なDXコンサルとは桁違いに低コスト」 |
| 面談後アクション | 期限なし | 全アクションに期限設定（当日/翌日/1週間以内） |

### 2-3. パートナー向け1枚資料の修正

| ファイル | 修正内容 |
|---------|---------|
| `tomoshi_partner_onepager.html` | 「月額運用コスト約5,000円」→「低コストで運用可能」 |
| `tomoshi_partner_onepager.md` | 同上 |

### 2-4. 渡邉氏・会社買取センターの事前リサーチ（新規作成）

**ファイル:** `tomoshi_kaitori_center_research.md`

主な発見:
- 渡邉智浩氏: 中小企業診断士＋MBA、株式会社タスクールPlus代表取締役
- 年間500本以上のセミナーを主催、延べ15,000人以上参加
- TBS「がっちりマンデー」出演、中小企業庁「創業スクール10選」表彰
- 会社買取センター: 「M&Aではなく買取」モデル。仲介手数料ゼロ
- 無形資産（顧客リスト、ノウハウ等）も買取対象
- 面談での切り出し方・訴求ポイントの提案付き

### 2-5. 診断レポートテンプレート（新規作成）

**ファイル:** `tomoshi_diagnosis_report_template.md`

戦略レビューでPhase 1最優先と特定されていた「診断結果に基づく詳細レポート」のテンプレート。
- 10領域別の評価表
- 優先改善ステップ（短期/中期）
- 業種別の仕組み化事例（製造業/建設/税理士/中古車/小売）
- TOMOSHIプログラムの紹介
- テンプレート変数（{{score}}等）で個別化可能

### 2-6. サイトのCSS不具合修正 (`index.html`)

**発見した不具合:** トップページの「自社実証」セクション（proofセクション）のCSSクラスが定義されていなかった。
- `proof`, `proof-lead`, `proof-grid`, `proof-card`, `proof-metric`, `proof-label`, `proof-desc`, `proof-note` のスタイルがindex.htmlのインラインCSSに欠落
- style.cssには定義があるが、index.htmlはstyle.cssを読み込んでいない（全インライン方式）
- 結果: 自社実証セクションが**完全にスタイル未適用**で表示されていた

**修正:** index.htmlのインラインCSSにproofセクションのスタイルを追加

---

## 3. ブランドガイド準拠チェック（修正後）

| ルール | 提案書 | 面談台本 | 1枚資料 | サイト |
|--------|--------|---------|---------|--------|
| 技術名を出さない | OK | OK | OK | OK |
| 原価を公開しない | OK | OK | OK | OK |
| TOMOSHIとTASは分離 | 連絡先をinfo@tomoshi.jpに変更済み | N/A | OK | OK |
| 盛らない | OK | OK | OK | OK |

---

## 4. 成果物一覧（全ファイルパス）

### 修正済みファイル
- `/mnt/c/Users/USER/Documents/_data/content/proposal_kaitori_center.md` -- 提案書（ブランドガイド準拠に修正）
- `/mnt/c/Users/USER/Documents/_data/content/meeting_script_kaitori_center.md` -- 面談台本（原価情報削除・期限追加）
- `/mnt/c/Users/USER/Documents/_data/content/tomoshi_partner_onepager.html` -- HTML版1枚資料（原価削除）
- `/mnt/c/Users/USER/Documents/_data/content/tomoshi_partner_onepager.md` -- MD版1枚資料（原価削除）
- `/mnt/c/Users/USER/Documents/_data/tomoshi-site/index.html` -- トップページ（proof CSS追加）
- `/mnt/c/Users/USER/Documents/_data/tas-automation/docs/tomoshi_meeting_review.md` -- 面談レビュー（チェックリスト更新）

### 新規作成ファイル
- `/mnt/c/Users/USER/Documents/_data/content/tomoshi_kaitori_center_research.md` -- 渡邉氏・会社買取センターの事前リサーチ
- `/mnt/c/Users/USER/Documents/_data/content/tomoshi_diagnosis_report_template.md` -- 診断レポートテンプレート

---

## 5. 残作業（ユーザー操作が必要なもの）

| 作業 | 担当 | タイミング |
|------|------|-----------|
| 加藤TLに渡邉氏への紹介温度感を確認 | ユーザー | 面談日確定前 |
| 面談形式（オンライン/対面）を確認 | ユーザー | 面談日確定後 |
| 提案書の日付を面談日に更新 | 自動化可能 | 面談日確定後 |
| 対面の場合: 提案書PDF印刷・名刺準備 | ユーザー | 面談前日 |
| tomoshi-site index.htmlの変更をデプロイ | git push | 確認後 |
| apple-touch-icon.png の作成・設置 | デザイン作業 | 優先度低 |

---

## 6. 戦略レビューのPhase 1チェックリスト進捗

| Phase 1施策 | ステータス |
|------------|-----------|
| 診断レポートテンプレートの作成 | **本セッションで完了** |
| apple-touch-icon.png の作成・設置 | 未着手（優先度低） |
| ブログ記事の公開日分散 | 未着手（効果限定的） |
| DKIM設定 | 未着手（メール配信開始前に対応） |
| Cloudflare Workerの動作確認 | 未着手（要テスト） |
