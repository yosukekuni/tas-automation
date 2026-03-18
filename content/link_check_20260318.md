# tokaiair.com リンク検証レポート
**実行日時**: 2026-03-18 23:35:23

## サマリー
| 項目 | 件数 |
|------|------|
| 投稿数 | 74 |
| 固定ページ数 | 68 |
| ユニーク内部リンク数 | 114 |
| 正常 (200) | 113 |
| リンク切れ | 1 |
| リダイレクト | 0 |

## 1. リンク切れ一覧

| URL | ステータス | リンク元ページ |
|-----|-----------|----------------|
| `https://tokaiair.com/services/dx-consulting/` | 404 | 土量コスト計算機 |

## 2. リダイレクト一覧

リダイレクトはありません。

## 3. 新規デプロイページ詳細検証

### `/drone-survey-cost-comparison/` [FAIL]
| チェック項目 | 結果 | 詳細 |
|-------------|------|------|
| HTTP Status | PASS | 200 |
| Title | PASS | ドローン測量 費用比較シミュレーター | 東海エアサービス - 東海エアサービス株式会社 |
| Meta Description | FAIL | MISSING |
| JSON-LD | PASS | 5件, valid=True, types=['unknown', 'ProfessionalService', 'Person', 'Organization', 'BreadcrumbList'] |
| 内部リンク | PASS | 切れ: 0件 |

### `/drone-survey-statistics/` [FAIL]
| チェック項目 | 結果 | 詳細 |
|-------------|------|------|
| HTTP Status | PASS | 200 |
| Title | PASS | 東海エアサービス 実績データ統計 | ドローン測量 - 東海エアサービス株式会社 |
| Meta Description | FAIL | MISSING |
| JSON-LD | PASS | 5件, valid=True, types=['unknown', 'ProfessionalService', 'Person', 'Organization', 'BreadcrumbList'] |
| 内部リンク | PASS | 切れ: 0件 |

### `/drone-survey-market-report/` [FAIL]
| チェック項目 | 結果 | 詳細 |
|-------------|------|------|
| HTTP Status | PASS | 200 |
| Title | PASS | 東海エリア ドローン測量 市場レポート（自社実績ベース）| 東海エアサービス - 東海エアサービス株式会社 |
| Meta Description | FAIL | MISSING |
| JSON-LD | PASS | 5件, valid=True, types=['unknown', 'ProfessionalService', 'Person', 'Organization', 'BreadcrumbList'] |
| 内部リンク | PASS | 切れ: 0件 |

### `/nagoya/` [FAIL]
| チェック項目 | 結果 | 詳細 |
|-------------|------|------|
| HTTP Status | PASS | 200 |
| Title | PASS | 名古屋市のドローン測量 | 東海エアサービス株式会社 - 東海エアサービス株式会社 |
| Meta Description | FAIL | MISSING |
| JSON-LD | PASS | 6件, valid=True, types=['unknown', 'ProfessionalService', 'Person', 'Organization', 'BreadcrumbList', 'unknown'] |
| 内部リンク | PASS | 切れ: 0件 |

### `/toyota/` [FAIL]
| チェック項目 | 結果 | 詳細 |
|-------------|------|------|
| HTTP Status | PASS | 200 |
| Title | PASS | 豊田市のドローン測量 | 東海エアサービス株式会社 - 東海エアサービス株式会社 |
| Meta Description | FAIL | MISSING |
| JSON-LD | PASS | 6件, valid=True, types=['unknown', 'ProfessionalService', 'Person', 'Organization', 'BreadcrumbList', 'unknown'] |
| 内部リンク | PASS | 切れ: 0件 |

### `/gifu-city/` [FAIL]
| チェック項目 | 結果 | 詳細 |
|-------------|------|------|
| HTTP Status | PASS | 200 |
| Title | PASS | 岐阜市のドローン測量 | 東海エアサービス株式会社 - 東海エアサービス株式会社 |
| Meta Description | FAIL | MISSING |
| JSON-LD | PASS | 6件, valid=True, types=['unknown', 'ProfessionalService', 'Person', 'Organization', 'BreadcrumbList', 'unknown'] |
| 内部リンク | PASS | 切れ: 0件 |

### `/tsu/` [FAIL]
| チェック項目 | 結果 | 詳細 |
|-------------|------|------|
| HTTP Status | PASS | 200 |
| Title | PASS | 津市のドローン測量 | 東海エアサービス株式会社 - 東海エアサービス株式会社 |
| Meta Description | FAIL | MISSING |
| JSON-LD | PASS | 6件, valid=True, types=['unknown', 'ProfessionalService', 'Person', 'Organization', 'BreadcrumbList', 'unknown'] |
| 内部リンク | PASS | 切れ: 0件 |

### `/shizuoka-city/` [FAIL]
| チェック項目 | 結果 | 詳細 |
|-------------|------|------|
| HTTP Status | PASS | 200 |
| Title | PASS | 静岡市のドローン測量 | 東海エアサービス株式会社 - 東海エアサービス株式会社 |
| Meta Description | FAIL | MISSING |
| JSON-LD | PASS | 6件, valid=True, types=['unknown', 'ProfessionalService', 'Person', 'Organization', 'BreadcrumbList', 'unknown'] |
| 内部リンク | PASS | 切れ: 0件 |

### `/case-library/cases/` [PASS]
| チェック項目 | 結果 | 詳細 |
|-------------|------|------|
| HTTP Status | PASS | 200 |
| Title | PASS | 事例・資料｜東海エアサービス株式会社 |
| Meta Description | PASS | 東海エアサービスは、ドローン測量・3次元データによる建設現場の課題を解決するデータコンサルティング会社です。施工実績185件超。翌日納品対応。 |
| JSON-LD | PASS | 1件, valid=True, types=['unknown'] |
| 内部リンク | PASS | 切れ: 0件 |

## 4. 判定

### 全体結果
- 内部リンク切れ: **1件**
- デプロイページ不合格: **8件**

### 対応要否
**要対応** - 上記の問題を修正してください。
