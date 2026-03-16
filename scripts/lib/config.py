"""
共通設定ロード

automation_config.json の読み込みと、WordPress認証ヘッダーの生成。

Usage:
    from lib.config import load_config, get_wp_auth

    cfg = load_config()
    auth = get_wp_auth(cfg)

設定ファイルの探索順:
    1. /mnt/c/Users/USER/Documents/_data/automation_config.json （ローカル実環境）
    2. scripts/automation_config.json （GitHub Actions / 相対パス）

GitHub Actions のプレースホルダー (${{...}}) 入りファイルはスキップする。
"""

import json
import base64
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent  # scripts/

# 探索パス（優先順）
CONFIG_SEARCH_PATHS = [
    Path("/mnt/c/Users/USER/Documents/_data/automation_config.json"),
    SCRIPT_DIR / "automation_config.json",
]


def load_config(extra_paths=None):
    """automation_config.json を読み込んで dict を返す。

    Args:
        extra_paths: 追加の探索パス（リスト）。CONFIG_SEARCH_PATHS より先に検索。

    Returns:
        dict: 設定辞書

    Raises:
        FileNotFoundError: どのパスにも見つからない場合
    """
    search = list(extra_paths or []) + CONFIG_SEARCH_PATHS
    last_cfg = None

    for p in search:
        p = Path(p)
        if not p.exists():
            continue
        with open(p) as f:
            cfg = json.load(f)
        # GitHub Actions テンプレートのプレースホルダーはスキップ
        if str(cfg.get("lark", {}).get("app_id", "")).startswith("${"):
            last_cfg = cfg
            continue
        return cfg

    # 全ファイルがプレースホルダーだった場合（GitHub Actions環境）
    if last_cfg is not None:
        return last_cfg

    raise FileNotFoundError(
        "automation_config.json not found in: "
        + ", ".join(str(p) for p in search)
    )


def get_wp_auth(cfg):
    """WordPress REST API 用の Basic 認証文字列を返す。

    Args:
        cfg: load_config() の戻り値

    Returns:
        str: Base64エンコード済み認証文字列（"Basic " プレフィックスなし）
    """
    user = cfg["wordpress"]["user"]
    pwd = cfg["wordpress"]["app_password"]
    return base64.b64encode(f"{user}:{pwd}".encode()).decode()


def get_wp_base_url(cfg):
    """WordPress REST API のベースURL（/wp/v2 なし）を返す。

    Args:
        cfg: load_config() の戻り値

    Returns:
        str: 例 "https://tokaiair.com/wp-json"
    """
    return cfg["wordpress"]["base_url"].replace("/wp/v2", "")


def get_wp_api_url(cfg):
    """WordPress REST API の /wp/v2 付きURLを返す。

    Args:
        cfg: load_config() の戻り値

    Returns:
        str: 例 "https://tokaiair.com/wp-json/wp/v2"
    """
    return cfg["wordpress"]["base_url"]
