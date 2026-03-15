# Core Web Vitals改善 設計書

作成日: 2026-03-15
ステータス: 設計完了・実装待ち
対象サイト: https://www.tokaiair.com/

## 概要

tokaiair.comのCore Web Vitals（LCP/FID→INP/CLS）を改善し、
検索ランキングとユーザー体験を向上させる。

## Core Web Vitals指標

| 指標 | 正式名 | 良好 | 要改善 | 不良 |
|------|--------|------|--------|------|
| LCP | Largest Contentful Paint | ≤2.5s | ≤4.0s | >4.0s |
| INP | Interaction to Next Paint | ≤200ms | ≤500ms | >500ms |
| CLS | Cumulative Layout Shift | ≤0.1 | ≤0.25 | >0.25 |

## 現状分析方法

### データ取得
1. **PageSpeed Insights API**: ラボデータ + CrUXフィールドデータ
2. **GA4**: Web Vitals イベント（既存ga4_analytics.pyで取得可能）
3. **Google Search Console**: CWVレポート

### 分析スクリプト（実装予定）

```python
# PageSpeed Insights API呼び出し
PSI_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
params = {
    "url": "https://www.tokaiair.com/",
    "strategy": "mobile",
    "category": "performance"
}
```

## 改善施策

### Phase 1: LCP改善（最優先）

#### 1-1. 画像最適化
- **WebP変換**: 未対応画像をWebP形式に変換
- **遅延読み込み**: ファーストビュー外の画像に `loading="lazy"`
- **ファーストビュー画像のプリロード**: `<link rel="preload" as="image">`
- **適切なサイズ指定**: width/height属性の明示（CLS対策も兼ねる）

#### 1-2. サーバーレスポンス改善
- **LiteSpeed Cache**: 既に導入済み。設定最適化
  - ページキャッシュTTL確認
  - オブジェクトキャッシュ有効化確認
- **TTFB目標**: 200ms以下

#### 1-3. レンダリングブロック排除
- **CSS**: クリティカルCSSのインライン化 + 残りの非同期読み込み
- **JavaScript**: `defer` / `async` 属性の適切な設定
- **フォント**: `font-display: swap` の確認

### Phase 2: INP改善

#### 2-1. JavaScript最適化
- **サードパーティスクリプト削減**: 不要なトラッキングコード除去
- **メインスレッドブロック削減**: 長時間タスクの分割
- **イベントハンドラ最適化**: debounce/throttle適用

#### 2-2. DOM最適化
- **DOM要素数削減**: 目標1,500要素以下
- **不要なプラグイン無効化**

### Phase 3: CLS改善

#### 3-1. レイアウトシフト防止
- **画像/動画のアスペクト比指定**: width/height属性必須
- **広告/埋め込みの予約領域確保**
- **Webフォント読み込み時のシフト防止**: `font-display: swap` + fallbackフォント設定
- **動的コンテンツの挿入位置**: ビューポート外に配置

## LiteSpeedキャッシュ設定チェックリスト

- [ ] ページキャッシュ: 有効
- [ ] CSSの結合・最小化: 有効
- [ ] JSの結合・最小化: 有効（ただし動作確認必須）
- [ ] 画像の遅延読み込み: 有効（ファーストビュー除外設定）
- [ ] WebP変換: 有効
- [ ] クリティカルCSS生成: 有効
- [ ] ブラウザキャッシュ: 有効（TTL: 30日）

## 実装ステップ

1. PageSpeed Insights APIで現状スコア取得（ベースライン記録）
2. Phase 1施策を実施（LiteSpeed設定 + 画像最適化）
3. 変更後にキャッシュパージ → 再計測
4. Phase 2/3は結果を見て優先度判断
5. GA4でフィールドデータの改善推移をモニタリング

## 注意事項

- CSS変更時: `inherit!important` 禁止（ボタン・フッター文字消える）
- 変更後: ユーザーにLiteSpeedキャッシュパージ依頼
- JS結合: 結合すると壊れるプラグインがあるため、個別テスト必須
- WordPress変更は `wp_safe_deploy.py` 経由
