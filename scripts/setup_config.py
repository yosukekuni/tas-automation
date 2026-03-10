#!/usr/bin/env python3
"""GitHub Actions用: 環境変数からautomation_config.jsonを生成"""
import json
import os
from pathlib import Path

config = {
    "lark": {
        "app_id": os.environ.get("LARK_APP_ID", ""),
        "app_secret": os.environ.get("LARK_APP_SECRET", ""),
        "crm_base_token": os.environ.get("CRM_BASE_TOKEN", ""),
        "web_analytics_base_token": os.environ.get("WEB_ANALYTICS_BASE_TOKEN", ""),
    },
    "google": {
        "service_account_json": "/tmp/google_sa.json",
        "ga4_property_id": os.environ.get("GA4_PROPERTY_ID", ""),
        "site_url": "https://www.tokaiair.com/",
    },
    "wordpress": {
        "base_url": "https://tokaiair.com/wp-json/wp/v2",
        "user": os.environ.get("WP_USER", ""),
        "app_password": os.environ.get("WP_APP_PASSWORD", ""),
    },
    "anthropic": {
        "api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
    },
    "notifications": {
        "lark_webhook_url": os.environ.get("LARK_WEBHOOK_URL", ""),
    },
}

out = Path(__file__).parent / "automation_config.json"
with open(out, "w") as f:
    json.dump(config, f, indent=2)
print(f"Config written to {out}")
