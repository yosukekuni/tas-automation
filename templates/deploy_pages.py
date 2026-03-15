#!/usr/bin/env python3
"""Deploy page content to WordPress via REST API."""
import json, sys, os, urllib.request, urllib.parse, base64

CONFIG_PATH = "/mnt/c/Users/USER/Documents/_data/automation_config.json"
TEMPLATE_PATH = "/mnt/c/Users/USER/Documents/_data/tas-automation/templates/page_template.html"
PAGES_DIR = "/mnt/c/Users/USER/Documents/_data/tas-automation/templates/pages"

PAGES = [
    {"slug": "company",      "page_id": 16,   "file": "company.html"},
    {"slug": "contact",      "page_id": 19,   "file": "contact.html"},
    {"slug": "case-library", "page_id": 5098, "file": "case-library.html"},
]

with open(CONFIG_PATH) as f:
    config = json.load(f)

wp = config["wordpress"]
base_url = wp["base_url"]
creds = base64.b64encode(f"{wp['user']}:{wp['app_password']}".encode()).decode()

# Read template
with open(TEMPLATE_PATH) as f:
    template = f.read()

results = []
for page in PAGES:
    page_file = os.path.join(PAGES_DIR, page["file"])
    with open(page_file) as f:
        page_content = f.read()
    
    # Build full HTML by replacing placeholder
    full_html = template.replace("__PAGE_CONTENT__", page_content)
    
    # For WP REST API, we send the page_content (inner HTML only), not the full template
    # The template (nav/footer/styles) is already in WP theme or handled by custom HTML page
    # Send full HTML as content
    url = f"{base_url}/pages/{page['page_id']}"
    
    data = urllib.parse.urlencode({"content": full_html}).encode()
    
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("User-Agent", "TAS-Automation/1.0")
    req.add_header("Authorization", f"Basic {creds}")
    
    try:
        resp = urllib.request.urlopen(req)
        result = json.loads(resp.read().decode())
        link = result.get("link", "N/A")
        print(f"OK: {page['slug']} (ID={page['page_id']}) -> {link}")
        results.append({"slug": page["slug"], "status": "ok", "link": link})
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"FAIL: {page['slug']} (ID={page['page_id']}) -> {e.code} {body[:300]}")
        results.append({"slug": page["slug"], "status": "error", "code": e.code, "detail": body[:300]})

print("\n--- Summary ---")
for r in results:
    print(f"  {r['slug']}: {r['status']} {r.get('link', r.get('detail', ''))}")
