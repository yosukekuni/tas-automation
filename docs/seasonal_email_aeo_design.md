# 季節メール自動送信 + AEO月次チェック 設計書

作成日: 2026-03-14

---

## 1. 季節メール自動送信（4月・10月）

### 1.1 概要

新年度（4月）・下期（10月）に、過去受注実績のある顧客（セグメントA/C群）へ測量計画確認メールを自動送信する。既存の `auto_followup_email.py` の構造を参考に、独立スクリプトとして実装する。

### 1.2 技術設計

#### スクリプト: `scripts/seasonal_email.py`

```
seasonal_email.py
  --dry-run    ドラフト生成のみ（デフォルト）
  --send       Gmail下書き作成 + 送信
  --list       対象顧客一覧のみ表示
  --season     april | october（自動判定も可）
```

#### 処理フロー

```
1. Lark API認証（tenant_access_token取得）
2. 受注台帳(tbldLj2iMJYocct6)から過去受注ありの取引先を抽出
3. 取引先(tblTfGScQIdLTYxA)でセグメントA/C群をフィルタ
4. 連絡先(tblN53hFIQoo4W8j)から担当者メールアドレス取得
5. メールログ(tblfBahatPZMJEM5)で直近60日以内送信済みを除外（重複防止）
6. Claude APIで顧客ごとにパーソナライズしたメール文面を生成
7. review_agent email チェック（CRITICAL判定なら送信中止）
8. Gmail下書き作成（HTML形式）
9. メールログに送信記録を書き込み
10. Lark Webhook通知（処理結果サマリー）
```

#### 対象顧客の抽出ロジック

```python
def extract_seasonal_targets(orders, accounts, contacts, email_logs):
    """
    抽出条件:
    - 受注台帳にレコードが存在する取引先
    - 取引先のセグメント = A群 or C群
    - 連絡先にメールアドレスが登録されている
    - 直近60日以内にメール送信していない
    - 商談ステージが「失注」「不在」でない
    """
```

#### 使用API

| API | 用途 | 呼び出し回数/実行 |
|-----|------|-------------------|
| Lark Bitable API | CRMデータ取得（4テーブル） | 4-8回（ページネーション） |
| Claude API (claude-sonnet-4-20250514) | メール文面生成 | 対象顧客数（想定10-30件） |
| Gmail API (MCP) | 下書き作成 | 対象顧客数 |
| Lark Bitable API | メールログ書き込み | 対象顧客数 |
| Lark Webhook | 完了通知 | 1回 |

#### セーフガード

- 1回の実行で最大30件まで（超過分は次回に繰り越し）
- 同一取引先への送信は60日間隔を強制
- review_agent emailチェック必須（CRITICALなら送信中止）
- `--dry-run`がデフォルト（明示的に`--send`しない限り送信しない）

### 1.3 実行スケジュール

#### GitHub Actions: `.github/workflows/seasonal_email.yml`

```yaml
name: Seasonal Survey Planning Email

on:
  schedule:
    # 4月第1週 月曜 09:00 JST (= 00:00 UTC)
    - cron: '0 0 6 4 1'   # 4/6前後の月曜（年により調整）
    # 10月第1週 月曜 09:00 JST
    - cron: '0 0 5 10 1'  # 10/5前後の月曜
  workflow_dispatch:
    inputs:
      season:
        description: 'Season: april or october'
        required: false
        default: ''
      mode:
        description: 'Mode: dry-run, send, list'
        required: false
        default: 'dry-run'

jobs:
  seasonal:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Setup config
        env:
          LARK_APP_ID: ${{ secrets.LARK_APP_ID }}
          LARK_APP_SECRET: ${{ secrets.LARK_APP_SECRET }}
          CRM_BASE_TOKEN: ${{ secrets.CRM_BASE_TOKEN }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          LARK_WEBHOOK_URL: ${{ secrets.LARK_WEBHOOK_URL }}
        run: python scripts/setup_config.py

      - name: Run seasonal email
        run: |
          SEASON="${{ github.event.inputs.season }}"
          MODE="${{ github.event.inputs.mode }}"
          ARGS=""
          if [ -n "$SEASON" ]; then ARGS="$ARGS --season $SEASON"; fi
          if [ -n "$MODE" ]; then ARGS="$ARGS --$MODE"; else ARGS="$ARGS --send"; fi
          python scripts/seasonal_email.py $ARGS

      - name: Upload drafts
        uses: actions/upload-artifact@v4
        with:
          name: seasonal-drafts-${{ github.run_number }}
          path: scripts/seasonal_drafts/
          retention-days: 30
        if: always()
```

**補足**: cron式は「4月/10月の特定日の月曜」指定だが、GitHub Actionsのcronは曜日とDOM両方指定するとOR条件になるため、実運用では以下いずれかで対応:

- **案A**: `cron: '0 0 1-7 4 1'`（4月1-7日の月曜）で第1月曜を狙う
- **案B**: `cron: '0 0 1 4 *'`（4/1固定）+ スクリプト内で曜日調整
- **案C**: `workflow_dispatch`のみにして、4月/10月に手動トリガー

推奨は**案C**（年2回なので手動トリガーが最も確実）。

### 1.4 メールテンプレート

#### 4月（新年度）テンプレート

Claude APIへのプロンプトに組み込むベーステンプレート:

```
件名：新年度の測量計画についてご挨拶 — 東海エアサービス

{担当者名} 様

いつもお世話になっております。
東海エアサービスの{営業担当名}でございます。

{前回受注内容}の際は大変お世話になりました。
新年度を迎え、本年度の測量・計測のご計画がございましたら、
ぜひお気軽にお声がけください。

昨年度からの変更点として、以下のサービスも強化しております。
{最新サービス情報 — Claude APIで動的生成}

ご計画の段階でのご相談でも構いません。
概算費用や工期のお見積もりも迅速に対応いたします。

何卒よろしくお願いいたします。

--
東海エアサービス株式会社
{営業担当名}
https://www.tokaiair.com/
```

#### 10月（下期）テンプレート

```
件名：下期の測量ご計画について — 東海エアサービス

{担当者名} 様

いつもお世話になっております。
東海エアサービスの{営業担当名}でございます。

{前回受注内容}では大変お世話になりました。
下期に入り、年度内に実施予定の測量・計測案件がございましたら、
年内のスケジュール確保のためにも早めのご相談をお勧めしております。

{季節性の提案 — 冬場の注意点、年度末納期対応など — Claude APIで動的生成}

ご検討中の案件がございましたら、概算費用含めご提案させていただきます。
お気軽にご連絡ください。

--
東海エアサービス株式会社
{営業担当名}
https://www.tokaiair.com/
```

#### Claude APIプロンプト設計

```python
SEASONAL_PROMPT = """あなたは東海エアサービス株式会社の営業担当 {rep_name} として、
季節の挨拶を兼ねた測量計画確認メールを作成してください。

【季節】{season_label}（{season_context}）
【会社情報】東海エアサービス株式会社 — ドローン測量（公共測量対応・i-Construction）
【過去取引】{order_history}
【顧客情報】{customer_name} / {customer_industry}

【ルール】
1. 件名と本文を出力（件名は「件名：」で始める）
2. 過去の取引内容に触れつつ、新規案件の相談を促す
3. 押し売りしない。「ご計画があれば」程度のトーン
4. 300文字以内の本文。敬語は丁寧すぎず
5. HTML形式で出力（<p>タグで段落区切り）
6. 署名ブロックを含める
"""
```

### 1.5 実装工数見積もり

| タスク | 工数 |
|--------|------|
| `seasonal_email.py` 本体 | 3時間 |
| 受注台帳データ取得+セグメント判定ロジック | 1時間 |
| Claude APIプロンプト調整+テスト | 1時間 |
| review_agent統合 | 0.5時間 |
| Gmail下書き作成（HTML形式） | 0.5時間 |
| メールログ書き込み | 0.5時間 |
| GitHub Actions workflow作成 | 0.5時間 |
| dry-runテスト+本番テスト | 1時間 |
| **合計** | **8時間** |

---

## 2. AEO（AI検索最適化）月次チェック

### 2.1 概要

主要AI検索エンジン（ChatGPT / Perplexity / Gemini）で「名古屋 ドローン測量」等の検索を月次実行し、自社（東海エアサービス）の言及有無・言及順位・言及内容を記録する。AEO施策の効果測定に使用。

### 2.2 技術設計

#### スクリプト: `scripts/aeo_monthly_check.py`

```
aeo_monthly_check.py
  --dry-run    チェックのみ（レポート生成なし）
  --report     レポート生成+Lark通知
  --query "検索ワード"   特定クエリのみテスト
```

#### 検索クエリリスト

```python
AEO_QUERIES = [
    # コアキーワード
    "名古屋 ドローン測量",
    "愛知県 ドローン測量会社",
    "名古屋 ドローン測量 費用",
    "愛知 ドローン 3次元測量",
    # サービス系
    "ドローン測量 i-Construction 愛知",
    "ドローン 土量計算 名古屋",
    "ドローン 点群測量 東海地方",
    # 競合比較系
    "ドローン測量会社 おすすめ 東海",
    "ドローン測量 外注 名古屋",
    # ニーズ系
    "建設現場 ドローン測量 見積もり",
    "公共測量 ドローン 愛知県",
]
```

#### 処理フロー

```
1. 各クエリについてAI検索APIを呼び出し
   - Perplexity API（sonar-pro）: 公式API利用
   - Claude API + Web検索: Claude with WebSearch tool
2. レスポンスから自社言及を解析
   - 「東海エアサービス」「tokaiair.com」の出現チェック
   - 言及位置（何番目に出現するか）
   - 言及コンテキスト（前後の文脈を抽出）
   - 競合他社の言及もカウント
3. 結果をLark Baseに記録（Web分析Base内に新テーブル）
4. 月次レポート生成 → Lark Webhook通知
```

#### 使用API

| API | 用途 | 呼び出し回数/実行 |
|-----|------|-------------------|
| Perplexity API (sonar-pro) | AI検索結果取得 | クエリ数（11回） |
| Claude API (claude-sonnet-4-20250514) | 結果分析+レポート生成 | 1-2回 |
| Lark Bitable API | 結果記録 | クエリ数+1 |
| Lark Webhook | レポート通知 | 1回 |

#### API選定根拠

| エンジン | 方式 | 月額コスト目安 |
|----------|------|---------------|
| **Perplexity API (sonar-pro)** | 公式API。引用元URL付き | $5/1000リクエスト = 11クエリ/月 約$0.06 |
| ChatGPT Web検索 | OpenAI APIのweb_search tool | $25/月 minimum（高い） |
| Gemini | Google AI Studio API | 無料枠あり |

**推奨**: Perplexity API単体で開始。引用URL付きで自社言及の検証精度が高い。コスト月$0.06未満。

#### データ保存構造

Web分析Base（Token: Vy65bp8Wia7UkZs8CWCjPSqJpyf）に以下テーブルを新設:

**テーブル名: AEOチェック結果**

| フィールド | 型 | 説明 |
|-----------|-----|------|
| チェック日 | 日付 | 実行日 |
| 検索クエリ | テキスト | 検索ワード |
| エンジン | テキスト | perplexity / chatgpt / gemini |
| 自社言及 | チェック | 言及あり=true |
| 言及順位 | 数値 | 何番目に言及されたか（0=言及なし） |
| 言及テキスト | テキスト | 言及箇所の前後文脈 |
| 引用URL | URL | 引用されたURL |
| 競合言及社数 | 数値 | 同一レスポンス内の競合他社数 |
| 全文レスポンス | テキスト | AI検索の全回答テキスト |

#### Perplexity API呼び出し

```python
def query_perplexity(query):
    """Perplexity sonar-pro APIで検索"""
    data = json.dumps({
        "model": "sonar-pro",
        "messages": [
            {"role": "user", "content": query}
        ]
    }).encode()

    req = urllib.request.Request(
        "https://api.perplexity.ai/chat/completions",
        data=data,
        headers={
            "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
            "Content-Type": "application/json",
        }
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        result = json.loads(r.read())
        content = result["choices"][0]["message"]["content"]
        citations = result.get("citations", [])
        return content, citations
```

#### 自社言及解析

```python
SELF_MARKERS = ["東海エアサービス", "tokaiair.com", "tokaiair", "TOKAI AIR"]

COMPETITOR_MARKERS = [
    "テラドローン", "ジャパン・インフラ・ウェイマーク", "スカイマティクス",
    "エアロセンス", "センシンロボティクス",
    # 東海地方の競合
]

def analyze_mention(content, citations):
    mentioned = any(m in content for m in SELF_MARKERS)
    cited = any(any(m in url for m in ["tokaiair.com"]) for url in citations)
    position = 0
    if mentioned:
        # 最初の言及位置（文字数ベースの相対位置）
        for marker in SELF_MARKERS:
            idx = content.find(marker)
            if idx >= 0:
                position = content[:idx].count("。") + 1  # 文単位の位置
                break
    competitor_count = sum(1 for c in COMPETITOR_MARKERS if c in content)
    return {
        "mentioned": mentioned or cited,
        "position": position,
        "competitor_count": competitor_count,
        "cited_urls": [u for u in citations if "tokaiair" in u],
    }
```

### 2.3 実行スケジュール

#### GitHub Actions: `.github/workflows/aeo_check.yml`

```yaml
name: AEO Monthly Check (1st of month 10:00 JST)

on:
  schedule:
    - cron: '0 1 1 * *'  # 01:00 UTC = 10:00 JST, 毎月1日
  workflow_dispatch:
    inputs:
      query:
        description: 'Specific query to test (optional)'
        required: false

jobs:
  aeo:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Setup config
        env:
          LARK_APP_ID: ${{ secrets.LARK_APP_ID }}
          LARK_APP_SECRET: ${{ secrets.LARK_APP_SECRET }}
          WEB_ANALYTICS_BASE_TOKEN: ${{ secrets.WEB_ANALYTICS_BASE_TOKEN }}
          PERPLEXITY_API_KEY: ${{ secrets.PERPLEXITY_API_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          LARK_WEBHOOK_URL: ${{ secrets.LARK_WEBHOOK_URL }}
        run: python scripts/setup_config.py

      - name: Run AEO check
        run: |
          QUERY="${{ github.event.inputs.query }}"
          if [ -n "$QUERY" ]; then
            python scripts/aeo_monthly_check.py --report --query "$QUERY"
          else
            python scripts/aeo_monthly_check.py --report
          fi

      - name: Upload report
        uses: actions/upload-artifact@v4
        with:
          name: aeo-report-${{ github.run_number }}
          path: scripts/aeo_reports/
          retention-days: 90
        if: always()
```

### 2.4 レポートテンプレート

#### Lark Webhook通知（月次サマリー）

```
AEO月次レポート（2026年4月）

■ 自社言及率: 5/11クエリ (45.5%)
  前月比: +2クエリ (+18.2pt)

■ クエリ別結果:
  [言及あり] 名古屋 ドローン測量 — 2番目に言及
  [言及あり] 愛知県 ドローン測量会社 — 1番目に言及
  [言及なし] ドローン測量 i-Construction 愛知
  ...

■ 引用URL:
  tokaiair.com/drone-survey/ — 3回引用
  tokaiair.com/earthwork-cost/ — 1回引用

■ 競合動向:
  テラドローン: 8/11クエリで言及
  エアロセンス: 4/11クエリで言及

■ 推奨アクション:
  - 「i-Construction 愛知」で言及なし → 関連コンテンツ強化を検討
  - 土量コスト記事が引用される頻度高い → 継続更新推奨
```

#### 詳細レポート（Artifact保存）

`scripts/aeo_reports/YYYYMM_aeo_report.json` に全結果をJSON保存。
月次比較用のトレンドデータとして蓄積。

### 2.5 実装工数見積もり

| タスク | 工数 |
|--------|------|
| `aeo_monthly_check.py` 本体 | 2時間 |
| Perplexity API連携 | 1時間 |
| 自社言及解析ロジック | 1時間 |
| Lark Base テーブル作成+書き込み | 1時間 |
| 月次レポート生成+Webhook通知 | 1時間 |
| GitHub Actions workflow作成 | 0.5時間 |
| テスト（dry-run + 本番） | 1時間 |
| **合計** | **7.5時間** |

---

## 3. 実装優先度・前提条件

### 新規Secrets（GitHub Actions）

| Secret名 | 用途 | 設計 |
|-----------|------|------|
| `PERPLEXITY_API_KEY` | AEOチェック | 新規取得必要 |

既存Secretsで対応可能: LARK_APP_ID, LARK_APP_SECRET, CRM_BASE_TOKEN, ANTHROPIC_API_KEY, WEB_ANALYTICS_BASE_TOKEN, LARK_WEBHOOK_URL

### 月額ランニングコスト

| 項目 | コスト |
|------|--------|
| 季節メール: Claude API (年2回 x 30件) | 約$0.30/年 |
| AEOチェック: Perplexity API (月11クエリ) | 約$0.06/月 = $0.72/年 |
| AEOチェック: Claude API (月1回分析) | 約$0.05/月 = $0.60/年 |
| **年間合計** | **約$1.62/年** |

### 実装順序

1. **AEO月次チェック（優先）** — 7.5時間
   - 効果測定は早期に始めるほどトレンドデータが蓄積される
   - Perplexity APIキー取得が前提
2. **季節メール（4月に間に合わせる）** — 8時間
   - 次の送信タイミングは2026年4月 → 実装期限3月末

**総工数: 15.5時間（2日程度）**
