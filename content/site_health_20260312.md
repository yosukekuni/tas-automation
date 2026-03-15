# tokaiair.com サイトヘルスチェック

**実施日**: 2026-03-12
**ステータス**: READ-ONLY 診断（変更なし）

---

## サマリー

| カテゴリ | 結果 |
|---------|------|
| SSL/リダイレクト | OK |
| ページ応答 | OK（全ページ200） |
| メタデータ | WARNING: /contact/ にmeta description未設定 |
| 構造化データ | OK（全主要ページにJSON-LD設置済み） |
| robots.txt | OK（制限なし） |
| WordPress REST API | OK |
| プラグイン | OK（14個稼働中） |
| SSL証明書 | WARNING: 2026-05-05 期限（あと54日） |

---

## 1. SSL/リダイレクトチェック

| テスト | 結果 |
|-------|------|
| http://tokaiair.com/ → https://tokaiair.com/ | 301 OK |
| http://www.tokaiair.com/ → https://tokaiair.com/ | 301 OK |
| https://tokaiair.com/about/ → /company/ | 301 OK |
| SSL証明書 | Let's Encrypt R13 |
| 証明書有効期間 | 2026-02-04 〜 2026-05-05 |
| SSL検証 | OK（ssl_verify_result=0） |

---

## 2. ページ応答チェック（全31ページ）

### 全200（正常応答）
- / (トップ), /services/, /services/uav-survey/, /services/3d-measurement/
- /services/infrared-inspection/, /services/dx-consulting/, /services/public-survey/
- /column/, /recruit/, /company/, /contact/, /faq/, /news/
- /tools/earthwork/, /tools/earthwork/calculator/, /tools/earthwork/register/, /tools/earthwork/login/
- /tools/woodchip-inventory-calculator/
- /case-library/, /case-library/cases/, /case-library/pricing/
- /case-library/whitepaper/, /case-library/whitepaper/resources/
- /terms/, /privacy-policy/, /members/
- /recruit/inside-sales/, /recruit/dx-consultant/, /recruit/pointcloud-engineer/, /recruit/uav-operator/

### 301リダイレクト（意図的）
| URL | リダイレクト先 | 備考 |
|-----|---------------|------|
| /cases/ | /事例・資料/cases/ | 日本語スラッグ含む（SEO上は要注意） |
| /tools/ | /tools-woodchip-inventory/ | リダイレクト先も200 OK |
| /about/ | /company/ | 設定済み |

### コラム記事（99件）
- サンプル5件を確認: 全て200 OK
- post-sitemap.xml に99件登録

---

## 3. ページ速度（基本チェック）

| 指標 | 値 |
|------|-----|
| TTFB（Time to First Byte） | 0.123秒 |
| 総レスポンス時間 | 0.415秒 |
| HTML サイズ | 212,503 bytes（約207KB） |
| HTML行数 | 833行 |

**評価**: TTFB 0.123秒は良好。HTMLサイズ207KBはやや大きいが、構造化データ（JSON-LD）が複数埋め込まれているため妥当。LiteSpeed Cache稼働中。

---

## 4. メタデータチェック

| ページ | title | meta description | 評価 |
|--------|-------|-----------------|------|
| / | ドローン測量・3D計測・赤外線調査なら東海エアサービス｜名古屋 | あり | OK |
| /services/ | 事業内容 - 東海エアサービス株式会社 | あり | OK |
| /services/uav-survey/ | ドローン測量 - 東海エアサービス株式会社 | あり | OK |
| /cases/ (→redirect) | - | - | リダイレクト |
| /column/ | コラム - 東海エアサービス株式会社 | あり | OK |
| /recruit/ | 採用 - 東海エアサービス株式会社 | あり | OK |
| /company/ | 会社情報 - 東海エアサービス株式会社 | あり | OK |
| /contact/ | お問い合わせ - 東海エアサービス株式会社 | **なし** | WARNING |

### /contact/ の問題点
- `<meta name="description">` タグが存在しない
- `og:description` は設定済み（「お問い合わせ - 東海エアサービス株式会社｜ドローン測量...」）
- Yoast SEOでmeta descriptionを個別設定すれば解決

---

## 5. 構造化データ（JSON-LD）

| ページ | スキーマタイプ |
|--------|---------------|
| / | Organization, FAQPage(26問), ProfessionalService, BreadcrumbList |
| /services/ | WebPage, BreadcrumbList, Organization, ProfessionalService |
| /services/uav-survey/ | WebPage, BreadcrumbList, WebSite, Organization, Service, Person |
| /cases/ (→redirect) | WebPage, BreadcrumbList, WebSite, Organization, ProfessionalService, Person |
| /column/ | WebPage, BreadcrumbList, WebSite, Organization, ProfessionalService, Person, ItemList |
| /recruit/ | WebPage, BreadcrumbList, WebSite, Organization, ProfessionalService, Person, JobPosting(4件) |
| /company/ | WebPage, Organization, ProfessionalService, BreadcrumbList, Person, PostalAddress |
| /contact/ | WebPage, BreadcrumbList, WebSite, Organization, ProfessionalService, Person |

**評価**: 全主要ページに適切な構造化データが設置されている。特にFAQPage(26問)、JobPosting(4件)、Service、ProfessionalServiceなどリッチリザルト対象スキーマが充実。

---

## 6. WordPress健全性

| 項目 | 状態 |
|------|------|
| WP REST API | アクセス可能 |
| WordPress バージョン | 6.9.4 |
| Yoast SEO | v27.1.1 稼働中 |
| LiteSpeed Cache | v7.8 稼働中 |
| Site Kit by Google | v1.174.0 稼働中 |
| IndexNow | v1.0.3 稼働中 |
| Redirection | v5.7.5 稼働中 |
| UpdraftPlus | v1.26.2 稼働中 |
| CookieYes GDPR | v3.4.0 稼働中 |

### 稼働中プラグイン一覧（14個）
1. Better Search Replace v1.4.10
2. Category Order and Taxonomy Terms Order v1.9.4
3. CMS Tree Page View v1.6.8
4. Code Snippets v3.9.5
5. CookieYes | GDPR Cookie Consent v3.4.0
6. IndexNow v1.0.3
7. LiteSpeed Cache v7.8
8. LLMS Full TXT Generator v2.0.6
9. Post Views Counter v1.7.8
10. Redirection v5.7.5
11. Site Kit by Google v1.174.0
12. UpdraftPlus v1.26.2
13. WP All Import v4.0.1
14. Yoast SEO v27.1.1

---

## 7. インデックス状況

### robots.txt
```
User-agent: *
Disallow:

Sitemap: https://tokaiair.com/sitemap_index.xml
```
- 制限なし（全ページクローラーアクセス可能）
- noindex指令なし

### サイトマップ構成
| サイトマップ | URL数 |
|-------------|-------|
| page-sitemap.xml | 32ページ |
| post-sitemap.xml | 99記事 |
| glossary-sitemap.xml | - |
| category-sitemap.xml | - |
| author-sitemap.xml | - |

### noindex チェック
- 全主要ページで `<meta name='robots' content='index, follow, ...'>` 確認
- 意図しないnoindexなし

---

## 8. 注意事項・改善推奨

### WARNING（対応推奨）

1. **`/contact/` にmeta description未設定**
   - og:descriptionはあるが、`<meta name="description">` が欠落
   - Google検索結果のスニペットに影響する可能性
   - 対応: Yoast SEOの編集画面でmeta descriptionを入力

2. **SSL証明書の期限（2026-05-05）**
   - 残り約54日。Let's Encryptは通常自動更新されるが、更新が失敗していないか確認推奨
   - サーバー側のcertbot/acme自動更新設定を確認

3. **`/cases/` のリダイレクト先が日本語スラッグ**
   - `/cases/` → `/事例・資料/cases/` にリダイレクト
   - URLにエンコードされた日本語（`%e4%ba%8b%e4%be%8b...`）が含まれる
   - SEO上はASCIIスラッグが推奨される

4. **HTMLサイズ 207KB**
   - JSON-LD構造化データが複数埋め込まれているため。深刻ではないがモバイル環境では最適化余地あり

### CRITICAL（なし）
- 重大な問題は検出されなかった

---

## 結論

tokaiair.com は全体的に健全な状態。全主要ページが正常応答し、構造化データ・SEOメタデータも充実している。TTFB 0.123秒は優秀。即座に対応が必要なCRITICAL問題はないが、`/contact/` のmeta description設定とSSL証明書の自動更新確認を推奨する。
