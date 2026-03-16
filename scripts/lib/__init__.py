"""
tas-automation 共通ライブラリ

既存スクリプトは変更しない（互換性維持）。
新しいスクリプトから以下のようにインポートして使う:

    from lib.lark_api import lark_get_token, lark_list_records, send_lark_dm
    from lib.config import load_config, get_wp_auth
    from lib.wp_api import wp_get_page, wp_update_post, wp_get_all_posts
"""
