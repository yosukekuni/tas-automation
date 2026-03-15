/**
 * Snippet: Theme Post Title H1→H2 Downgrade
 *
 * X-T9テーマのテンプレートが wp-block-post-title を H1 で出力するため、
 * コンテンツ内の本来のH1と重複する問題を修正。
 * render_block フィルターで wp-block-post-title ブロックの出力を
 * H1→H2 に書き換える。
 *
 * 対象: 固定ページ・投稿・カスタム投稿タイプ（フロントエンドのみ）
 * 除外: トップページ（H1がない）、管理画面
 *
 * Scope: front-end
 * Priority: 10
 */
add_filter('render_block', function ($html, $block) {
    // wp-block-post-title ブロックのみ対象
    if ($block['blockName'] !== 'core/post-title') {
        return $html;
    }

    // H1タグをH2に変換（属性は維持）
    $html = preg_replace(
        '/<h1(\s|>)/i',
        '<h2$1',
        $html,
        1
    );
    $html = preg_replace(
        '/<\/h1>/i',
        '</h2>',
        $html,
        1
    );

    return $html;
}, 10, 2);
