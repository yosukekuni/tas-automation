#!/usr/bin/env python3
"""Import 29 missing companies from crm_not_found.json into Lark CRM deal table."""

import json
import re
import sys
import requests
from datetime import datetime

# === Config ===
CONFIG_PATH = "/mnt/c/Users/USER/Documents/_data/automation_config.json"
INPUT_PATH = "/tmp/crm_not_found.json"
CRM_BASE_ID = "BodWbgw6DaHP8FspBTYjT8qSpOe"
DEAL_TABLE_ID = "tbl1rM86nAw9l3bP"

# Rep IDs
REP_IDS = {
    "masaki": "ou_6ee633b968b9229655813af6e3a47e9f",
    "niimi": "ou_189dc637b61a83b886d356becb3ae18e",
}

# Score to stage mapping
SCORE_TO_STAGE = {
    "Hot": "見積検討",
    "Warm": "ヒアリング",
    "Cold": "リード獲得",
}

# Company suffixes
COMPANY_PATTERNS = [
    r"株式会社", r"（株）", r"\(株\)",
    r"有限会社", r"（有）", r"\(有\)",
    r"合同会社", r"コンサルタンツ", r"コンサルタント",
    r"工業", r"航業",
]

# Site keywords
SITE_KEYWORDS = ["工事", "建設工事", "改修", "整備事業", "小学校", "中学校", "改良"]

# Area keywords for tamura reassignment
GIFU_MIE_KEYWORDS = [
    "岐阜", "三重", "四日市", "桑名", "いなべ", "多度", "東員",
    "北勢", "大安", "鈴鹿", "亀山", "津市",
]


def get_tenant_token(app_id: str, app_secret: str) -> str:
    url = "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": app_id, "app_secret": app_secret})
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Token error: {data}")
    return data["tenant_access_token"]


def is_address(name: str) -> bool:
    return bool(re.match(r"[〒０-９0-9]", name.strip()))


def extract_company_from_mixed(name: str):
    """Try to extract company name from strings like '矢野建設（株）四日市市中野町排水工事'.
    Returns (company_name, site_name) or (None, None) if no company found.
    """
    # Branch-only suffixes (not real sites)
    branch_only = ["本社", "支店", "営業所", "事務所"]

    # Pattern: Company（株）SiteName or Company株式会社SiteName
    for suffix in ["（株）", "(株)"]:
        if suffix in name:
            idx = name.index(suffix) + len(suffix)
            company = name[:idx].strip()
            site = name[idx:].strip()
            # Only split if the remaining part is a real site (not just branch name)
            if site and not any(site.strip().endswith(b) for b in branch_only):
                # Check if it contains site keywords
                if any(kw in site for kw in SITE_KEYWORDS):
                    return company, site
            return None, None

    # For 株式会社, it can be prefix (株式会社XXX) or suffix (XXX株式会社)
    if "株式会社" in name:
        idx = name.index("株式会社")
        if idx == 0:
            # Prefix: 株式会社XXX → check what follows
            after = name[len("株式会社"):].strip()
            # Check if there's a site component after the company part
            # e.g. no site keywords → entire string is company name
            if not any(kw in after for kw in SITE_KEYWORDS + ["営業所", "支店", "本社"]):
                return None, None  # whole thing is company name
            # Has site-like content after prefix company
            return name, None
        else:
            # Suffix: XXX株式会社YYY
            end_idx = idx + len("株式会社")
            company = name[:end_idx].strip()
            site = name[end_idx:].strip()
            # Strip whitespace variants
            site = site.lstrip("　 ")
            # Only split if remaining part is a real site (not branch descriptor)
            if site and not any(site.rstrip("　 ").endswith(b) for b in branch_only):
                if any(kw in site for kw in SITE_KEYWORDS):
                    return company, site
            return None, None

    return None, None


def has_company_indicator(name: str) -> bool:
    for pat in ["株式会社", "（株）", "(株)", "有限会社", "（有）", "(有)", "合同会社"]:
        if pat in name:
            return True
    return False


def is_site_name(name: str) -> bool:
    for kw in SITE_KEYWORDS:
        if kw in name:
            return True
    return False


def classify_record(rec: dict) -> dict:
    """Classify a record and return enriched info."""
    original = rec["original"]
    result = {
        "type": None,       # "company", "site", "address", "mixed"
        "company_name": None,
        "site_name": None,
        "deal_name": None,
        "original": original,
    }

    # 1) Address check
    if is_address(original):
        result["type"] = "address"
        location = rec.get("location", original)
        result["deal_name"] = location
        return result

    # 2) Mixed: contains company suffix AND site content
    if has_company_indicator(original):
        company, site = extract_company_from_mixed(original)
        if company and site:
            result["type"] = "mixed"
            result["company_name"] = company
            result["site_name"] = site
            result["deal_name"] = company
        else:
            # Pure company name (possibly with branch info)
            result["type"] = "company"
            # Clean branch/location suffixes
            clean = original
            for suffix in ["本社", "　本社", " 本社"]:
                clean = clean.replace(suffix, "").strip()
            # Keep branch info in location but use base company for deal
            result["company_name"] = original
            result["deal_name"] = original
        return result

    # 3) Known company names without standard suffixes
    company_like = ["大マンションコンサルタント", "東海共同測量設計"]
    for c in company_like:
        if c in original:
            result["type"] = "company"
            result["company_name"] = original
            result["deal_name"] = original
            return result

    # 4) Site name check
    if is_site_name(original):
        result["type"] = "site"
        result["site_name"] = original
        # Try hearing for company info
        hearing = rec.get("hearing", "")
        # Look for company names in hearing (must be proper company-like names)
        # Exclude false positives like 予算組, 足場組み, etc.
        hearing_companies = re.findall(r'([ァ-ヶー\u4e00-\u9fff]{2,}(?:建設|工業|工務店))', hearing)
        # Also look for X組 but filter out non-company matches
        hearing_kumi = re.findall(r'([ァ-ヶー\u4e00-\u9fff]{2,}組)\b', hearing)
        hearing_kumi = [k for k in hearing_kumi if k not in ("予算組", "足場組", "仮組")]
        hearing_companies = hearing_companies + hearing_kumi
        if hearing_companies:
            result["company_name"] = hearing_companies[0]
            result["deal_name"] = f"{hearing_companies[0]}_{original}"
        else:
            result["deal_name"] = original
        return result

    # 5) Plain name (school name etc without 工事)
    if any(kw in original for kw in ["小学校", "中学校"]):
        result["type"] = "site"
        result["site_name"] = original
        result["deal_name"] = original
        return result

    # 6) Default: treat as company
    result["type"] = "company"
    result["company_name"] = original
    result["deal_name"] = original
    return result


def get_rep_id(rec: dict, classified: dict) -> str:
    """Determine the rep ID for a record."""
    rep = rec.get("rep", "unknown")

    # tamura → reassign by area
    if rep == "tamura":
        text = rec["original"] + " " + rec.get("location", "") + " " + rec.get("hearing", "")
        for kw in GIFU_MIE_KEYWORDS:
            if kw in text:
                return REP_IDS["masaki"]
        return REP_IDS["niimi"]

    # unknown → niimi
    if rep == "unknown" or rep not in REP_IDS:
        return REP_IDS["niimi"]

    return REP_IDS[rep]


def get_stage(score: str) -> str:
    if score in SCORE_TO_STAGE:
        return SCORE_TO_STAGE[score]
    return "リード獲得"


def build_record(rec: dict, classified: dict) -> dict:
    """Build a Lark Bitable record."""
    visit = rec.get("visit", "")
    try:
        visit_date = datetime.strptime(visit, "%Y/%m/%d %H:%M:%S")
        date_suffix = visit_date.strftime("%Y/%m/%d")
    except (ValueError, TypeError):
        date_suffix = datetime.now().strftime("%Y/%m/%d")

    deal_name = f"{classified['deal_name']}_{date_suffix}"
    rep_id = get_rep_id(rec, classified)
    stage = get_stage(rec.get("score", ""))

    fields = {
        "商談名": deal_name,
        "担当営業": [{"id": rep_id}],
        "商談ステージ": stage,
    }

    return {"fields": fields}


def main():
    dry_run = "--execute" not in sys.argv

    # Load config
    with open(CONFIG_PATH) as f:
        config = json.load(f)
    lark_cfg = config["lark"]

    # Load records
    with open(INPUT_PATH) as f:
        records = json.load(f)

    print(f"Loaded {len(records)} records from {INPUT_PATH}")
    print(f"Mode: {'DRY RUN' if dry_run else 'EXECUTE'}")
    print("=" * 80)

    # Classify and build
    lark_records = []
    for i, rec in enumerate(records):
        classified = classify_record(rec)
        lark_rec = build_record(rec, classified)

        rep_name = rec.get("rep", "unknown")
        rep_id = get_rep_id(rec, classified)
        rep_display = "masaki" if rep_id == REP_IDS["masaki"] else "niimi"

        print(f"\n[{i+1:2d}] {rec['original']}")
        print(f"     Type: {classified['type']}")
        if classified["company_name"]:
            print(f"     Company: {classified['company_name']}")
        if classified["site_name"]:
            print(f"     Site: {classified['site_name']}")
        print(f"     Deal: {lark_rec['fields']['商談名']}")
        print(f"     Stage: {lark_rec['fields']['商談ステージ']}  (score: {rec.get('score', 'N/A')})")
        print(f"     Rep: {rep_name} → {rep_display}")

        lark_records.append(lark_rec)

    print("\n" + "=" * 80)
    print(f"Total records to create: {len(lark_records)}")

    if dry_run:
        print("\n*** DRY RUN - no records created. Use --execute to create records. ***")
        return

    # Get token
    print("\nGetting Lark tenant token...")
    token = get_tenant_token(lark_cfg["app_id"], lark_cfg["app_secret"])
    print("Token acquired.")

    # Batch create (max 500 per batch, we have 29)
    url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{CRM_BASE_ID}/tables/{DEAL_TABLE_ID}/records/batch_create"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    batch_size = 50
    created = 0
    errors = 0

    for start in range(0, len(lark_records), batch_size):
        batch = lark_records[start:start + batch_size]
        payload = {"records": batch}

        print(f"\nCreating batch {start // batch_size + 1} ({len(batch)} records)...")
        resp = requests.post(url, headers=headers, json=payload)
        data = resp.json()

        if data.get("code") == 0:
            created += len(batch)
            print(f"  Success: {len(batch)} records created")
        else:
            errors += len(batch)
            print(f"  ERROR: {data.get('msg', 'Unknown error')}")
            print(f"  Full response: {json.dumps(data, ensure_ascii=False, indent=2)}")

    print(f"\n{'=' * 80}")
    print(f"Results: {created} created, {errors} errors, {len(lark_records)} total")


if __name__ == "__main__":
    main()
