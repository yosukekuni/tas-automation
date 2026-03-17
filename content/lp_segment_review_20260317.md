# セグメント別LP精査レポート
日時: 2026-03-17
対象: 625f5b4コミットで作成されたLP3ページ

---

## 対象LP一覧

| LP | URL | WP ID | Status |
|-----|-----|-------|--------|
| 官公庁向け | https://tokaiair.com/lp/government/ | 6880 | publish |
| 不動産向け | https://tokaiair.com/lp/real-estate/ | 6882 | publish |
| 点検向け | https://tokaiair.com/lp/inspection/ | 6884 | publish |

---

## 設計書との整合性チェック

設計書: `docs/additional_lp_design.md`

### 構成セクション比較

| セクション | 設計書 | government | real-estate | inspection |
|-----------|--------|------------|-------------|------------|
| H1 | OK | OK | OK | OK |
| 課題提起(3つ) | OK | OK | OK | OK |
| ソリューション(3-4つ) | OK | OK(4つ) | OK(4つ) | OK(4つ) |
| 実績/導入事例 | OK | OK(3件) | OK(2件) | OK(2件) |
| 料金目安 | OK | OK(4行) | OK(5行) | OK(6行) |
| ご利用の流れ | OK | OK(6ステップ) | OK(6ステップ) | OK(6ステップ) |
| クロージングCTA | OK | OK | OK | OK |
| 構造化データ | 設計書に記載なし | Service+FAQ+HowTo+LocalBusiness+Breadcrumb | 同左 | 同左 |

全LP: 設計書の構成を忠実に再現済み。構造化データは設計書以上の品質で追加。

---

## SEO/AEO品質チェック結果

### 1. title / meta description

| LP | title | meta description | 問題 |
|----|-------|-----------------|------|
| government | 官公庁向けドローン測量・点検｜公共測量対応 \| 東海エアサービス | 公共測量作業規程準拠のドローン測量... | **修正済み**: Yoast titleで重複ブランド名(-東海エアサービス株式会社)を解消。meta description未設定だったが設定完了。 |
| real-estate | 不動産向けドローン撮影｜眺望パノラマ・物件空撮 \| 東海エアサービス | マンション眺望撮影・360度パノラマ... | **修正済み**: 同上 |
| inspection | ドローン点検｜赤外線外壁調査・太陽光パネル・インフラ点検 \| 東海エアサービス | 足場不要のドローン点検... | **修正済み**: 同上 |

### 2. H1/H2構造

全LP共通:
- H1: 1つ（適切）
- H2: 7-8個（課題提起/ソリューション/仕様/実績/料金/流れ/CTA）
- H3: ソリューション内で使用（階層構造適切）
- 問題なし

### 3. CTA配置

設計書指定: ファーストビュー直下 / 中間 / ページ下部
実装: 3箇所に配置済み。電話+フォーム+面談予約の段階的CTA。

**修正済み**: government/real-estateで「土量計算ツールを試す」CTAが混入していたが除去。
- 土量計算ツールはこれらのセグメントには無関係
- inspection LPは問題なし（元から含まれていない）

### 4. 内部リンク

| LP | 設計書指定 | 実装 | 状態 |
|----|-----------|------|------|
| government | /services/uav-survey/ + /services/3d-measurement/ + /lp/consultant/ | 全て実装 | OK |
| real-estate | /services/uav-survey/ + ギャラリー(要新設) | /services/uav-survey/のみ | ギャラリー未新設(設計書で「要新設」と明記) |
| inspection | /services/infrared-inspection/ + /services/3d-measurement/ | 全て実装 | OK |

### 5. 構造化データ

全LP共通で以下を実装:
- `Service` スキーマ（サービス名・説明）
- `FAQPage` スキーマ（3問3答）
- `HowTo` スキーマ（6ステップ）
- `LocalBusiness` スキーマ（名称・電話・住所・対応エリア）
- `BreadcrumbList` スキーマ

Yoast自動生成の構造化データ（WebPage/Organization/WebSite）とも共存。
AEO対応として十分な品質。

---

## 実施した修正

### 修正1: Yoast SEO meta description設定（全3ページ）
- API: `tas/v1/pagemeta/<id>` (key: `_yoast_wpseo_metadesc`)
- 全LP: 設計書の仕様通りのdescriptionを設定

### 修正2: Yoast SEO title設定（全3ページ）
- API: `tas/v1/pagemeta/<id>` (key: `_yoast_wpseo_title`)
- Yoast自動生成の「- 東海エアサービス株式会社」重複を解消

### 修正3: 不要CTA除去（government/real-estate）
- 「土量計算ツールを試す」リンク（/earthwork-calculator/）を除去
- wp_safe_deploy.py経由でデプロイ（review_agent OK）
- バックアップ: backups/lp_government_backup_20260317.html, backups/lp_real-estate_backup_20260317.html

---

## リードマグネット設計状況

設計書には「資料DL」がCTA候補として記載されているが、ダウンロード資料（リードマグネット）は未作成。

### 推奨リードマグネット（Phase3以降）

| LP | 資料名案 | 形式 | 目的 |
|----|---------|------|------|
| government | 「ドローン測量 公共事業導入ガイド」 | PDF | i-Construction対応の検討資料 |
| real-estate | 「マンション眺望撮影 サンプルギャラリー」 | PDF/Webページ | 撮影品質の訴求 |
| inspection | 「ドローン点検 vs 足場設置 コスト比較表」 | PDF | コスト削減の定量エビデンス |

現状はフォームCTA + 電話CTAで十分機能するが、
コンバージョン率向上のため段階的に資料DLを追加することを推奨。

---

## 残課題

| 項目 | 優先度 | 内容 |
|------|-------|------|
| LiteSpeedキャッシュパージ | 高 | meta description変更を反映するため要パージ（ユーザー手作業） |
| サンプルギャラリーページ新設 | 中 | real-estate LP内部リンク先（設計書で「要新設」） |
| リードマグネット資料作成 | 低 | PDF資料のコンテンツ制作 |
| IndexNow通知 | 中 | 3ページのURL変更をBing/Googleに通知 |

---

## 品質判定

**PASS** - 3ページとも設計書の仕様を忠実に実装済み。
meta description未設定という重大なSEO欠陥を修正し、不要CTAも除去。
構造化データ・内部リンク・CTA配置はいずれも高品質。
