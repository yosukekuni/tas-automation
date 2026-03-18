# SEO 検索順位1位奪取 戦略書

**作成日**: 2026-03-18
**対象サイト**: tokaiair.com
**目標**: 主要4クエリで検索順位1位を獲得

---

## 1. 現状分析サマリー

| クエリ | 現在順位 | 1位サイト | 1位の強み | TASの課題 |
|--------|---------|-----------|----------|----------|
| 名古屋 ドローン測量 | 2位 | drone-digitalarts.jp | titleに「名古屋」明記、JUIDA資格、全国許可 | titleに「名古屋」なし、Schema不足 |
| 愛知県 ドローン測量会社 | 2位 | jace603.jp | 「愛知」がtitle/H1に明記、施工事例多数 | 「愛知県」のクエリに対応するページなし |
| ドローン測量 費用 | 10位 | skysurvey-navi.com/knowledge/cost.html | 3,500語の網羅的コンテンツ、測量士監修E-E-A-T、45+内部リンク | コンテンツ量不足、費用ページのドメイン権威不足 |
| ドローン 土量計算 | 2位 | 不明 | - | FAQPage schema未実装（サービスページ） |

---

## 2. 競合詳細分析

### 2-1. drone-digitalarts.jp（名古屋 ドローン測量 1位）

**SEO要素:**
- title: 「名古屋のドローン撮影空撮で調査測量点検ならドローンデジタルアーツへ」
- H1: 「最先端の点検・測量技術」
- Schema: WebSite型のみ（最低限）
- コンテンツ量: 約1,200-1,400語
- CTA: 「お見積り、お問合せはこちら」x3、電話番号明記

**E-E-A-T:**
- JUIDA 無人航空機安全運航管理者/操縦技能士
- 第3級陸上特殊無線技士
- 国交省全国飛行許可
- 名古屋商工会議所/愛知中小企業同友会

**勝てるポイント:**
- Schema.orgが最低限→TASの方がリッチ化できる
- コンテンツ量が少ない→TASの方が専門記事群が充実
- 「測量」特化ではない（撮影・空撮がメイン）→TASは測量専門

**負けているポイント:**
- titleに「名古屋」が入っている（TASのサービスページには入っていない）
- 電話番号がCTA内に目立つ
- ブログ投稿で最新事例を定期更新

### 2-2. jace603.jp（愛知県 ドローン測量会社 1位）

**SEO要素:**
- title: 「愛知で測量なら「株式会社J.ace」| 最新技術を導入した高精度の測量」
- H1: 「愛知の測量「株式会社J.ace」- 短時間・高精度の成果を提供します」
- Schema: なし
- コンテンツ量: 約800-900語
- 内部リンク: 25-30

**E-E-A-T:**
- 測量業 第(2)-3586号（測量業者登録あり）
- 名古屋市「立ち直り支援推進企業」認定
- 大学病院・電力施設・自治体案件の事例

**勝てるポイント:**
- Schema.orgが全くない→TASが実装すれば圧倒的優位
- コンテンツ量が少ない（800語）
- ドローン測量専門ではない（総合測量会社）

**負けているポイント:**
- title/H1に「愛知」が入っている
- 施工事例が具体的（大学病院、電力施設等）
- YouTube活用

### 2-3. skysurvey-navi.com（ドローン測量 費用 1位）

**SEO要素:**
- title: 「ドローン測量を依頼した場合の費用目安」
- H1: 同上
- Schema: WebPage型 + reviewedBy（測量士情報）
- コンテンツ量: 約3,200-3,500語（費用ページ）/トップは8,000-10,000語
- 内部リンク: 45+
- FAQ: 別ページに用意

**E-E-A-T:**
- 測量士・土地家屋調査士 柳和樹氏が監修
- 1973年創業の柳土木設計事務所
- 国土地理院・国交省引用

**勝てるポイント:**
- アフィリエイト/ナビサイト型で実業者ではない→TASは実業者として信頼性が高い
- 価格が一般論→TASは自社実勢価格を出せる
- 地域特化できていない→TASは「名古屋・東海エリア」で特化可能

**負けているポイント:**
- コンテンツ量が圧倒的（3,500語 vs TASの費用ページ）
- 構造化データの監修者情報が充実
- 内部リンク数が多い（サイト全体のトピック網羅性）

---

## 3. 即実行施策（Priority: HIGH）

### 3-1. サービスページ（/services/uav-survey/）のSEO強化

**現状:**
- SEO Title: 「ドローン測量 - 東海エアサービス株式会社」
- SEO Desc: 「名古屋の東海エアサービスによるドローン測量。RTK/PPK対応で+-3cm精度...」
- Schema: Organization のみ
- FAQPage schema: なし
- LocalBusiness: なし
- Service schema: なし

**改善案:**
1. **SEO Title変更**: 「名古屋のドローン測量｜+-3cm高精度・最短翌日｜東海エアサービス」
   - 理由: 「名古屋」をtitle先頭に配置（競合1位と同じパターン）、精度と速度のUSPを含める

2. **Meta Description変更**: 「名古屋・愛知県のドローン測量なら東海エアサービス。RTK/PPK対応で+-3cm精度、最短翌日納品。土量算出・出来形管理・i-Construction対応。測量業者登録済み・国交省包括許可取得。料金15万円〜。無料見積り受付中。」
   - 理由: 「愛知県」追加、料金・資格を明示、CTA「無料見積り」

3. **構造化データ追加**:
   - LocalBusiness schema（地域SEO強化）
   - Service schema（サービス詳細）
   - FAQPage schema（FAQ Q&A）
   - BreadcrumbList schema

### 3-2. 費用ページ（/info/drone-survey-cost-nagoya/）の強化

**現状:**
- SEO Title: 「ドローン測量の費用相場｜名古屋・東海エリアの実勢価格」（良好）
- Schema: Article + FAQPage + ProfessionalService（良好）
- コンテンツ量: 不明（schemaでは27語となっているが実際はもっと多いはず）

**改善案:**
1. **SEO Title変更**: 「ドローン測量の費用相場【2026年版】名古屋・東海エリア実勢価格と料金表」
   - 理由: 年号追加で鮮度アピール、「料金表」キーワード追加

2. **コンテンツ加筆**:
   - 他社比較表（一般論として）
   - 写真測量 vs レーザー測量の費用比較（skysurvey-naviが持っている情報）
   - 公共測量マニュアルに基づく積算要素（権威性向上）
   - 費用を下げるコツ（ユーザー価値）

### 3-3. 土量計算ページの強化

**対象ページ:**
- /tools/earthwork/（土量コスト計算機）
- /articles/drone-earthwork-volume/（土量計算記事）
- /column/earthwork-cost/（土量コスト完全ガイド）

**改善案:**
1. /tools/earthwork/ の **SEO Title変更**: 「ドローン土量計算｜無料で残土コスト即算出｜東海エアサービス」
   - 理由: 「ドローン 土量計算」のクエリに直接合致させる

### 3-4. 「愛知県 ドローン測量会社」対策

**現状**: このクエリに直接対応するページがない

**改善案:**
1. ホームページ（/）のmeta descriptionに「愛知県」を含める（既に含んでいるか確認必要）
2. サービスページの構造化データに「areaServed」として愛知県を明記
3. 中期: 「愛知県のドローン測量」専用LPの作成を検討

---

## 4. 構造化データ改善詳細

### 4-1. サービスページに追加すべきSchema

```json
{
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "LocalBusiness",
      "@id": "https://tokaiair.com/#localbusiness",
      "name": "東海エアサービス株式会社",
      "description": "名古屋のドローン測量・3D計測・赤外線調査の専門会社",
      "url": "https://tokaiair.com/",
      "telephone": "+81-50-7117-7141",
      "email": "info@tokaiair.com",
      "address": {
        "@type": "PostalAddress",
        "streetAddress": "植園町1-9-3",
        "addressLocality": "名古屋市名東区",
        "addressRegion": "愛知県",
        "postalCode": "465-0077",
        "addressCountry": "JP"
      },
      "geo": {
        "@type": "GeoCoordinates",
        "latitude": 35.1715,
        "longitude": 137.0042
      },
      "areaServed": [
        {"@type": "State", "name": "愛知県"},
        {"@type": "State", "name": "岐阜県"},
        {"@type": "State", "name": "三重県"},
        {"@type": "State", "name": "静岡県"}
      ],
      "priceRange": "¥150,000〜",
      "openingHours": "Mo-Fr 09:00-18:00",
      "hasCredential": [
        {"@type": "EducationalOccupationalCredential", "credentialCategory": "測量業者登録"},
        {"@type": "EducationalOccupationalCredential", "credentialCategory": "全省庁統一資格"},
        {"@type": "EducationalOccupationalCredential", "credentialCategory": "国土交通省包括飛行許可"}
      ]
    },
    {
      "@type": "Service",
      "@id": "https://tokaiair.com/services/uav-survey/#service",
      "name": "ドローン測量",
      "description": "RTK/PPK対応のドローン測量。+-3cm精度で土量算出・出来形管理・GCP最適化に対応",
      "provider": {"@id": "https://tokaiair.com/#localbusiness"},
      "serviceType": "ドローン測量",
      "areaServed": [
        {"@type": "State", "name": "愛知県"},
        {"@type": "State", "name": "岐阜県"},
        {"@type": "State", "name": "三重県"},
        {"@type": "State", "name": "静岡県"},
        {"@type": "Country", "name": "日本"}
      ],
      "offers": {
        "@type": "Offer",
        "priceSpecification": {
          "@type": "PriceSpecification",
          "price": "150000",
          "priceCurrency": "JPY",
          "description": "基本料金15万円〜（面積・条件により変動）"
        }
      }
    },
    {
      "@type": "BreadcrumbList",
      "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "ホーム", "item": "https://tokaiair.com/"},
        {"@type": "ListItem", "position": 2, "name": "事業内容", "item": "https://tokaiair.com/services/"},
        {"@type": "ListItem", "position": 3, "name": "ドローン測量", "item": "https://tokaiair.com/services/uav-survey/"}
      ]
    }
  ]
}
```

---

## 5. 中期施策（1-3ヶ月）

### 5-1. コンテンツ強化
1. **費用ページの大幅加筆**（目標: 3,000語以上）
   - 写真測量 vs レーザー測量の詳細比較
   - 公共測量の積算基準解説
   - 実案件ベースの費用事例（匿名化）
   - 「費用を抑えるコツ」セクション追加

2. **「愛知県のドローン測量」専用ページ作成**
   - 愛知県内の施工実績マップ
   - 地域特性に応じた測量ポイント
   - 愛知県の建設市場動向

3. **事例ページの充実**
   - 各案件にbefore/afterデータ
   - コスト削減率・工期短縮率の定量データ
   - 顧客の声（テキスト or 動画）

### 5-2. 内部リンク強化
- サービスページ → 関連記事への相互リンク
- 記事群からサービスページへのCTAリンク
- 用語集からの関連ページリンク
- FAQ → 詳細記事へのリンク

### 5-3. 被リンク獲得戦略
1. **業界団体・協会**: 愛知県測量設計業協会等への加盟・掲載
2. **自治体**: 名古屋市の企業紹介ページ
3. **メディア掲載**: 建設業界メディアへの寄稿
4. **パートナー相互リンク**: 建設コンサル・ゼネコンとの相互リンク
5. **ツール被リンク**: 土量計算機が自然にリンクされる仕組み（埋め込みウィジェット等）

### 5-4. ローカルSEO
1. **Googleビジネスプロフィール最適化**
   - カテゴリ: 「測量会社」「ドローンサービス」
   - 写真: 現場作業風景・機材・成果物
   - 投稿: 週1回の事例・技術情報
   - レビュー: 顧客にレビュー依頼

2. **NAP一貫性**: 全プラットフォームで社名・住所・電話番号を統一

---

## 6. 実装計画

### Phase 1: 即実行（本日） -- 2026-03-18実施済み
- [x] 競合分析完了（4社の詳細SEO分析）
- [x] サービスページ title最適化: 「名古屋のドローン測量｜±3cm高精度・最短翌日｜東海エアサービス」
- [x] サービスページ meta desc最適化: 「名古屋・愛知県」を明記、料金・資格・CTA含む
- [x] 費用ページ title最適化: 「【2026年版】」年号追加、「料金表」キーワード追加
- [x] 土量計算ページ title最適化: 「ドローン土量計算」キーワード明記
- [x] 土量計算記事 title最適化: 「ドローン土量計算の方法」に変更
- [x] ホームページ meta desc: 「愛知県名古屋市」を先頭に追加
- [x] IndexNow送信完了（5 URLs）
- [x] Schema JSON-LDデータをWPオプション tas_uav_survey_schema に保存済み
- [ ] **要手動**: WP管理画面でSnippet 28を以下コードに差替え＋有効化（WAFブロックのためAPI経由不可）:

```php
// Snippet 28: Yoast Schema Graph に LocalBusiness + Service + FAQ を追加
add_filter('wpseo_schema_graph', function($graph, $context) {
    if (is_admin() || is_feed()) return $graph;
    if (!is_page('uav-survey')) return $graph;
    $json = get_option('tas_uav_survey_schema', '');
    if (empty($json)) return $graph;
    $data = json_decode($json, true);
    if (!is_array($data) || empty($data['@graph'])) return $graph;
    foreach ($data['@graph'] as $piece) { $graph[] = $piece; }
    return $graph;
}, 11, 2);
```

### Phase 2: 今週中
- [ ] 費用ページのコンテンツ加筆
- [ ] 全サービスページのBreadcrumbList統一
- [ ] 内部リンク強化

### Phase 3: 1ヶ月以内
- [ ] 「愛知県のドローン測量」専用ページ作成
- [ ] 事例ページの充実
- [ ] Googleビジネスプロフィール最適化

### Phase 4: 3ヶ月以内
- [ ] 被リンク獲得施策実行
- [ ] 定期的な順位モニタリングと改善
- [ ] 新規コンテンツの定期投稿

---

## 7. KPI・効果測定

| 指標 | 現在 | 目標（1ヶ月） | 目標（3ヶ月） |
|------|------|-------------|-------------|
| 「名古屋 ドローン測量」 | 2位 | 1位 | 1位維持 |
| 「愛知県 ドローン測量会社」 | 2位 | 1位 | 1位維持 |
| 「ドローン測量 費用」 | 10位 | 5位以内 | 3位以内 |
| 「ドローン 土量計算」 | 2位 | 1位 | 1位維持 |
| サービスページCTR | - | +20% | +40% |
| 問い合わせ数 | - | +15% | +30% |

---

*本戦略書は実施結果に基づき随時更新する*
