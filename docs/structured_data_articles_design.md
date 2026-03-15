# 記事#5-#15 構造化データ追加 設計書

作成日: 2026-03-15
ステータス: 設計完了・実装待ち

## 概要

tokaiair.com の記事#5-#15にArticle Schema（構造化データ）を追加する。
FAQスキーマ（別タスクで完了済み）とは異なり、記事本体のArticle/TechArticle Schemaを対象とする。

## 背景

- FAQスキーマは `seo_auto_optimizer` で全記事に適用済み（Row 49完了）
- 本タスクは記事本文に対するArticle Schemaの追加
- WAFブロックのためWP REST API直接更新ではなくSnippet経由が必要

## 対象構造化データ

### Article Schema (JSON-LD)

```json
{
  "@context": "https://schema.org",
  "@type": "TechArticle",
  "headline": "記事タイトル",
  "author": {
    "@type": "Organization",
    "name": "東海エアサービス株式会社",
    "url": "https://www.tokaiair.com/"
  },
  "publisher": {
    "@type": "Organization",
    "name": "東海エアサービス株式会社",
    "logo": {
      "@type": "ImageObject",
      "url": "https://www.tokaiair.com/wp-content/uploads/logo.png"
    }
  },
  "datePublished": "2025-XX-XX",
  "dateModified": "2026-XX-XX",
  "description": "記事の概要",
  "mainEntityOfPage": {
    "@type": "WebPage",
    "@id": "記事URL"
  }
}
```

### 追加候補
- `proficiencyLevel`: "Beginner" / "Expert"（TechArticle固有）
- `BreadcrumbList`: パンくずリスト構造化データ

## 実装方式

### WAFブロック対策
tokaiair.comのWAFがWP REST APIのHTML含むPUTリクエストをブロックする。

**方式: Code Snippets Plugin（#54）経由**
1. PHP関数でArticle Schemaを `<head>` に自動挿入
2. Snippet #54に条件分岐付きJSON-LD出力コードを追加
3. 記事IDベースで対象記事のみに適用

### PHP Snippet コード（案）

```php
function tas_article_schema() {
    if (!is_single()) return;

    global $post;
    $target_ids = [5,6,7,8,9,10,11,12,13,14,15]; // 対象記事ID
    if (!in_array($post->ID, $target_ids)) return;

    $schema = [
        '@context' => 'https://schema.org',
        '@type' => 'TechArticle',
        'headline' => get_the_title(),
        'author' => [
            '@type' => 'Organization',
            'name' => '東海エアサービス株式会社',
            'url' => 'https://www.tokaiair.com/'
        ],
        'publisher' => [
            '@type' => 'Organization',
            'name' => '東海エアサービス株式会社',
            'logo' => [
                '@type' => 'ImageObject',
                'url' => 'https://www.tokaiair.com/wp-content/uploads/logo.png'
            ]
        ],
        'datePublished' => get_the_date('c'),
        'dateModified' => get_the_modified_date('c'),
        'description' => get_the_excerpt(),
        'mainEntityOfPage' => [
            '@type' => 'WebPage',
            '@id' => get_permalink()
        ]
    ];

    echo '<script type="application/ld+json">' .
         json_encode($schema, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) .
         '</script>';
}
add_action('wp_head', 'tas_article_schema');
```

### API経由での追加可否
- **直接API更新**: WAFブロックにより不可
- **Code Snippets API**: Snippet #54の更新はGitHub Actions経由で可能（要検証）
- **推奨**: 管理画面からSnippet #54にPHPコードを手動追加

## 実装ステップ

1. 対象記事ID（#5-#15）の正確なpost IDを確認
2. PHPコードをSnippet #54に追加（管理画面 or API）
3. Google Search Consoleで構造化データのバリデーション確認
4. LiteSpeedキャッシュパージ依頼
