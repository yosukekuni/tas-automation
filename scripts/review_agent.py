"""
汎用レビューエージェント (壁打ちBot)
====================================
Agent 1が作成 → review_agent.py が自動チェック → 問題あれば修正指示

使い方:
  # 記事HTMLをレビュー
  python review_agent.py article content.html

  # メール文面をレビュー
  python review_agent.py email draft.txt

  # CSS/Snippetをレビュー
  python review_agent.py css snippet.css

  # 標準入力から
  echo "content" | python review_agent.py article -

  # JSON結果を取得
  python review_agent.py article content.html --json
"""

import sys
import os
import json
import argparse
import urllib.request
import urllib.error
from pathlib import Path

# Exponential Backoff: 全API呼び出しにリトライ機能を適用
import sys as _sys; _sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from lib.retry import patch_urlopen; patch_urlopen()

# レビュー観点定義
REVIEW_PROFILES = {
    "article": {
        "name": "記事公開チェック",
        "checks": [
            "ダークモード(黒背景)でテーブルのテキストが読めるか。is-style-stripesのストライプ行のコントラスト。ただしCSS変数(var(--xxx))使用時はテーマ側で対応済みと判断しWARNINGに留める",
            "テーブルのヘッダー(thead)に適切な背景色があるか。注意: WordPressはthead/tbody/caption/scopeタグを保存時に除去するため、これらの欠落はWARNING（CRITICALにしない）",
            "内部リンク・外部リンクが存在する場合、URLが妥当か（/soil-volume/ 等の壊れたパスがないか）",
            "CTAセクション（お問い合わせ・電話番号・予約リンク）が記事末尾に存在するか",
            "構造化データ(JSON-LD)がある場合、JSONとして正しいか",
            "meta description が設定されているか（Yoast SEO）",
            "画像のalt属性が設定されているか",
            "H1が1つだけ存在するか。H2-H3の階層が正しいか",
            "電話番号がtel:リンクになっているか",
            "TOMOSHIとTASのブランドが混在していないか（tomoshi.jpの記事にtokaiair、またはその逆）",
        ],
        "severity_guide": "表示崩れ・リンク切れ・ブランド混在はCRITICAL。SEO系・アクセシビリティ構造（thead/scope欠落）・リンク先の存在未確認・H階層の軽微な問題はWARNING。CRITICALは実際にユーザーに害がある問題のみ。"
    },
    "email": {
        "name": "メール送信チェック",
        "checks": [
            "宛先のメールアドレスが正しい形式か",
            "TOMOSHIの案件なのにtokaiair.comから送信していないか（ブランド分離）",
            "TASの案件なのにtomoshi.jpから送信していないか",
            "敬語・丁寧語が適切か。失礼な表現がないか",
            "金額・日付・名前などの固有情報が正しいか（プレースホルダーが残っていないか）",
            "署名が適切か（ブランドに合った署名）",
            "添付ファイルへの言及があるのに添付がない、またはその逆",
            "請求書の場合：振込先情報は自社のものを記載しているか（相手に聞いていないか）",
        ],
        "severity_guide": "ブランド混在・宛先間違い・金額間違いはCRITICAL。敬語はWARNING。"
    },
    "css": {
        "name": "CSS/Snippet変更チェック",
        "checks": [
            "ダークモード(prefers-color-scheme:dark)での表示が考慮されているか",
            "モバイル(max-width:768px)での表示が考慮されているか",
            "!importantの乱用がないか",
            "既存のCSS変数(var(--fg), var(--brand)等)を使っているか、ハードコード色を使っているか",
            "LiteSpeed Cacheの最適化で壊れる可能性があるか（DOMContentLoaded等）",
            "WAFにブロックされるパターンが含まれていないか（preg_replace, base64_decode, <script>直書き等）",
            "既存のSnippetと競合しないか（同じフック・同じセレクタ）",
        ],
        "severity_guide": "WAFブロック・既存機能破壊はCRITICAL。ダークモード未対応はWARNING。"
    },
    "crm": {
        "name": "CRM/データ変更チェック",
        "checks": [
            "テーブルIDが正しいBaseを指しているか（TAS CRM vs TOMOSHI CRM vs タスク管理）",
            "フィールド名が既存テーブルと一致しているか",
            "バッチ削除/更新の場合、対象レコードが正しいか（全件削除になっていないか）",
            "商談報告フォーム(vew6ijuGYp)を変更していないか",
        ],
        "severity_guide": "データ消失リスクはCRITICAL。フィールド名不一致はWARNING。"
    },
    "deploy": {
        "name": "デプロイ/公開チェック",
        "checks": [
            "git pushの対象ブランチが正しいか",
            "秘密情報（API key, password等）がコミットに含まれていないか",
            "automation_config.jsonがコミット対象に入っていないか",
            ".envファイルがコミット対象に入っていないか",
        ],
        "severity_guide": "秘密情報漏洩はCRITICAL。ブランチ間違いはWARNING。"
    }
}


def load_config():
    """Load API config"""
    config_paths = [
        Path("/mnt/c/Users/USER/Documents/_data/automation_config.json"),
        Path(os.environ.get("AUTOMATION_CONFIG", "")),
        Path("automation_config.json"),
        Path("scripts/automation_config.json"),
    ]
    for p in config_paths:
        if p.exists():
            return json.loads(p.read_text())
    raise FileNotFoundError("automation_config.json not found")


def call_review_api(content: str, profile: dict, config: dict) -> dict:
    """Call Claude API (Haiku) for review — urllib only, no requests dependency"""
    api_key = config["anthropic"]["api_key"]

    checks_text = "\n".join(f"  {i+1}. {c}" for i, c in enumerate(profile["checks"]))

    prompt = f"""あなたは品質レビュー担当のAIです。以下のコンテンツを厳密にチェックしてください。

## レビュー種別: {profile["name"]}

## チェック項目:
{checks_text}

## 重要度ガイド: {profile["severity_guide"]}

## レビュー対象コンテンツ:
```
{content[:15000]}
```

## 出力形式 (JSON):
{{
  "verdict": "OK" または "NG",
  "issues": [
    {{
      "severity": "CRITICAL" または "WARNING",
      "check_number": チェック項目番号,
      "description": "問題の説明",
      "fix_suggestion": "修正案"
    }}
  ],
  "summary": "全体の要約（1-2文）"
}}

CRITICALが1つでもあればverdict=NG。WARNINGのみならverdict=OK（ただしissuesに記載）。
問題がなければissues=[]でverdict=OK。
JSONのみを出力してください。"""

    data = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 2000,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=data,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result_text = json.loads(resp.read())["content"][0]["text"]

    # Parse JSON from response (handle markdown code blocks)
    if "```json" in result_text:
        result_text = result_text.split("```json")[1].split("```")[0]
    elif "```" in result_text:
        result_text = result_text.split("```")[1].split("```")[0]

    return json.loads(result_text.strip())


def review(profile_name: str, content: str, output_json: bool = False) -> dict:
    """Run a review and return results"""
    if profile_name not in REVIEW_PROFILES:
        available = ", ".join(REVIEW_PROFILES.keys())
        raise ValueError(f"Unknown profile: {profile_name}. Available: {available}")

    profile = REVIEW_PROFILES[profile_name]
    config = load_config()
    result = call_review_api(content, profile, config)

    if not output_json:
        # Pretty print
        verdict = result["verdict"]
        icon = "✅" if verdict == "OK" else "❌"
        print(f"\n{icon} [{profile['name']}] {verdict}")
        print(f"   {result['summary']}")

        if result.get("issues"):
            print()
            for issue in result["issues"]:
                sev_icon = "🔴" if issue["severity"] == "CRITICAL" else "🟡"
                print(f"   {sev_icon} [{issue['severity']}] チェック#{issue['check_number']}: {issue['description']}")
                if issue.get("fix_suggestion"):
                    print(f"      → {issue['fix_suggestion']}")
        print()

    return result


def main():
    parser = argparse.ArgumentParser(description="汎用レビューエージェント（壁打ちBot）")
    parser.add_argument("profile", choices=list(REVIEW_PROFILES.keys()),
                        help="レビュー種別")
    parser.add_argument("input", nargs="?", default="-",
                        help="レビュー対象ファイル（- で標準入力）")
    parser.add_argument("--json", action="store_true",
                        help="JSON形式で出力")
    parser.add_argument("--list-profiles", action="store_true",
                        help="利用可能なプロファイル一覧")
    args = parser.parse_args()

    if args.list_profiles:
        for name, profile in REVIEW_PROFILES.items():
            print(f"  {name:12} - {profile['name']} ({len(profile['checks'])}項目)")
        return

    # Read content
    if args.input == "-":
        content = sys.stdin.read()
    else:
        content = Path(args.input).read_text(encoding="utf-8")

    if not content.strip():
        print("Error: Empty content", file=sys.stderr)
        sys.exit(1)

    result = review(args.profile, content, output_json=args.json)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))

    # Exit code: 0=OK, 1=NG
    sys.exit(0 if result["verdict"] == "OK" else 1)


if __name__ == "__main__":
    main()
