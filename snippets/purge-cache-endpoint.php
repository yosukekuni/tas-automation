/**
 * TAS API: LiteSpeed Cache Purge Endpoint
 *
 * REST API: POST /wp-json/tas/v1/purge-cache
 * Body: {"action": "purge_all"} or {"action": "purge_url", "url": "/path/"}
 *
 * 認証: WordPress Application Password (Basic Auth)
 * 権限: manage_options (管理者のみ)
 *
 * Code Snippets プラグインに登録して使用する。
 */
add_action('rest_api_init', function () {
    register_rest_route('tas/v1', '/purge-cache', [
        'methods'             => 'POST',
        'callback'            => 'tas_purge_cache_handler',
        'permission_callback' => function () {
            return current_user_can('manage_options');
        },
    ]);
});

function tas_purge_cache_handler($request) {
    $action = $request->get_param('action') ?: 'purge_all';

    // LiteSpeed Cache プラグインが有効か確認
    if (!has_action('litespeed_purge_all') && !class_exists('LiteSpeed\Purge')) {
        return new WP_REST_Response([
            'success' => false,
            'message' => 'LiteSpeed Cache plugin is not active',
        ], 200);
    }

    switch ($action) {
        case 'purge_all':
            do_action('litespeed_purge_all');
            return new WP_REST_Response([
                'success' => true,
                'message' => 'All cache purged',
                'action'  => 'purge_all',
                'time'    => current_time('mysql'),
            ], 200);

        case 'purge_url':
            $url = $request->get_param('url');
            if (empty($url)) {
                return new WP_REST_Response([
                    'success' => false,
                    'message' => 'url parameter is required for purge_url action',
                ], 200);
            }
            do_action('litespeed_purge_url', $url);
            return new WP_REST_Response([
                'success' => true,
                'message' => "URL cache purged: {$url}",
                'action'  => 'purge_url',
                'url'     => $url,
                'time'    => current_time('mysql'),
            ], 200);

        default:
            return new WP_REST_Response([
                'success' => false,
                'message' => "Unknown action: {$action}",
            ], 200);
    }
}
