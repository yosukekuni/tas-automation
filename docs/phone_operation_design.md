# TAS 電話運用改善 設計書

作成日: 2026-03-14

---

## 1. 現状の課題

| 項目 | 現状 | リスク |
|------|------|--------|
| 電話番号 | 050-7117-7141（ララコール）1番号のみ | TAS/TOMOSHI両方で使用 → ブランド混在 |
| 転送先 | 國本携帯に転送 | 営業時間外も着信、対応負荷集中 |
| 電話後の記録 | CRMへの手動入力（任意） | 入力漏れ → 商談追跡不能 |
| 予約手段 | 電話中心 | スケジュール調整の手間、機会損失 |

---

## 2. 番号分離案

### 2.1 ララコール追加番号の料金（改定後）

| 契約形態 | 月額 | 備考 |
|----------|------|------|
| 個人LaLa Call（現行） | 429円/番号 | 2025/7/1改定（旧110円） |
| 2番号目追加 | +429円/月 | 別eoID必要 or mineo回線追加 |
| ビジネスLaLa Call | 500円/5番号 | 対象ネット契約あれば無料 |

### 2.2 推奨案: 個人LaLa Call 2番号目追加

**コスト: +429円/月（年5,148円）**

| 用途 | 番号 | 備考 |
|------|------|------|
| TAS（ドローン測量） | 050-7117-7141（既存） | tokaiair.com に掲載中 |
| TOMOSHI（AI業務改善） | 050-XXXX-XXXX（新規取得） | tomoshi.jp に掲載 |

### 2.3 追加番号取得手順

1. **新しいeoIDを作成**（別メールアドレスで登録）
   - info@tomoshi.jp など事業用メールを使用
2. LaLa Call公式サイト（https://lalacall.jp/procedure/）から申込
3. アプリインストール → 新eoIDでログイン → 050番号選択
4. 確認コード電話を受けて4桁入力 → 完了
5. TOMOSHI用の転送設定（國本携帯 or 別端末）
6. tomoshi.jp の電話番号表記を新番号に差し替え

### 2.4 代替案: ビジネスLaLa Call移行

- eo光/mineo契約があれば5番号まで月額500円（無料の場合あり）
- 法人申込: 0120-944-345 に電話 → 申込書送付
- **判断**: 現時点では個人2番号の方が手続き簡単でコスト同等。将来3番号以上必要になったらビジネス版検討

---

## 3. Phase 1: Scheduler予約誘導強化（電話依存の削減）

### 3.1 目的
電話問い合わせの一部をLark Scheduler経由のWeb予約に誘導し、スケジュール調整コストと電話対応負荷を削減する。

### 3.2 実装箇所

#### (A) tokaiair.com 問い合わせページにSchedulerリンク追加

問い合わせフォームの上部または電話番号の近くに、以下の誘導ブロックを追加:

```html
<!-- Scheduler予約誘導ブロック -->
<div style="background: #f0f7ff; border: 2px solid #0066cc; border-radius: 8px; padding: 20px; margin-bottom: 24px; text-align: center;">
  <p style="font-size: 16px; font-weight: bold; color: #0066cc; margin-bottom: 8px;">
    ご都合の良い日時をお選びいただけます
  </p>
  <p style="font-size: 14px; color: #333; margin-bottom: 16px;">
    お電話よりもスムーズにご予約いただけます。<br>
    ご希望の日時を選択するだけで、担当者との打ち合わせが確定します。
  </p>
  <a href="[LARK_SCHEDULER_URL]" target="_blank"
     style="display: inline-block; background: #0066cc; color: #fff; padding: 12px 32px; border-radius: 6px; text-decoration: none; font-size: 16px; font-weight: bold;">
    Web予約はこちら（無料）
  </a>
  <p style="font-size: 12px; color: #888; margin-top: 8px;">
    24時間いつでもご予約可能です
  </p>
</div>
```

**デプロイ**: wp_safe_deploy.py 経由でWordPressに反映

#### (B) メールフッターにSchedulerリンク追加

既存のナーチャリングメール・フォローアップメールのテンプレートに予約リンクを追加:

対象スクリプト:
- `scripts/auto_followup_email.py`
- `scripts/deal_thankyou_email.py`
- `scripts/email_nurturing_sequences.py`
- `scripts/lead_nurturing.py`
- `scripts/quote_followup.py`

フッター追記例:
```
▶ 打ち合わせのご予約: [LARK_SCHEDULER_URL]
  24時間Web予約可能です
```

#### (C) 名刺・チラシへの二次元コード追加
- Scheduler予約URLの二次元コードを名刺裏面・チラシに印刷
- 次回名刺発注時に対応

### 3.3 期待効果
- 電話問い合わせの20-30%をWeb予約に誘導（目標）
- スケジュール調整の往復メール・電話を削減
- 営業時間外の予約受付が可能に

---

## 4. Phase 2: 電話後の商談報告フォーム + リマインド

### 4.1 フロー設計

```
電話着信（ララコール転送）
  ↓
國本 or 営業が対応
  ↓
通話終了
  ↓ （30分タイマー開始）
  ↓
CRM商談テーブルに報告入力？
  ├─ YES → 完了（CRMモニターが検知 → 確認通知）
  └─ NO  → 30分後にLark Botリマインド送信
              ↓
           60分後に2回目リマインド
              ↓
           未入力のまま翌日 → 日次サマリーに未報告件数として表示
```

### 4.2 実装方針

#### (A) 商談報告フォーム（Lark Base フォーム）

既存の商談テーブル（tbl1rM86nAw9l3bP）のフォームビューを使用:

必須フィールド:
- 商談名（自動: 取引先名 + 日付）
- 取引先（リンク）
- 接触チャネル: 「電話（着信）」「電話（発信）」を選択肢に追加
- ヒアリング内容（まとめ）
- 温度感スコア
- 次回アクション

フォームURL: ブックマーク化 + Lark Bot のクイックアクションに設定

#### (B) crm_monitor への電話報告リマインド機能追加

`lark_crm_monitor.py` に以下のチェックを追加:

```python
def check_phone_report_missing(token):
    """
    電話着信後の商談報告未入力チェック

    ロジック:
    - 商談テーブルで接触チャネル=「電話」のレコードを取得
    - 直近の電話着信時刻と、最新の電話商談レコード作成時刻を比較
    - 着信から30分以上経過 & 未報告 → リマインド送信

    制約:
    - ララコールAPIに着信履歴APIがないため、手動トリガーまたは
      「電話あり」ボタン（Lark Bot）で着信を記録する方式を採用
    """
    pass
```

#### (C) 「電話あり」ボタン方式（推奨）

ララコールに着信履歴APIがないため、以下のシンプルな方式を採用:

1. Lark Bot に「電話あり」コマンドを追加（lark_command_executor.py拡張）
2. 電話対応後、Larkチャットで「電話あり [会社名]」と送信
3. Bot が30分タイマーを設定
4. 30分後に商談テーブルをチェック → 未入力ならリマインド送信

```
ユーザー: 電話あり 和合コンサルタント
Bot: 了解。30分後に商談報告チェックします。
     → 報告フォーム: [URL]

（30分後、未入力の場合）
Bot: ⚠️ 和合コンサルタントとの電話から30分経過。商談報告をお願いします。
     → 報告フォーム: [URL]
```

#### (D) 代替案: CRMモニター定期チェック方式

15分間隔の既存crm_monitorに組み込み:
- 商談テーブルで「接触チャネル=電話」かつ「ヒアリング内容=空」のレコードを検出
- 作成から30分以上経過していればリマインド

**判断**: まずは(C)のLark Botコマンド方式を実装。運用が定着したら(D)の自動検出も追加。

### 4.3 lark_command_executor.py への追加コマンド

```python
# 電話報告リマインドコマンド
COMMANDS["電話あり"] = {
    "handler": "handle_phone_call",
    "description": "電話対応を記録し、30分後に商談報告リマインドを送信",
    "usage": "電話あり [会社名]",
}
```

実装上の注意:
- GitHub Actionsは15分間隔実行のため、正確な30分タイマーは不可
- 代わりに: 電話記録をstate JSONに保存 → 次回実行時に30分経過チェック
- 15分間隔なので実質15-30分後のリマインドになるが許容範囲

---

## 5. コスト試算

| 項目 | 月額 | 年額 | 備考 |
|------|------|------|------|
| 既存ララコール | 429円 | 5,148円 | TAS用（改定後料金） |
| TOMOSHI用追加番号 | 429円 | 5,148円 | 新eoID作成 |
| Scheduler | 0円 | 0円 | Lark標準機能 |
| 商談報告Bot拡張 | 0円 | 0円 | 既存インフラ内 |
| **合計増分** | **+429円** | **+5,148円** | |

※ 現行固定費 693,369円/月に対して +0.06% の増加。ブランド混在リスク排除の対価として十分合理的。

---

## 6. 実装優先順位

| 優先度 | タスク | 工数 | 効果 |
|--------|--------|------|------|
| P1 | TOMOSHI用追加番号取得 | 30分 | ブランド混在リスク即時排除 |
| P1 | tokaiair.com にSchedulerリンク追加 | 1時間 | 電話依存削減の起点 |
| P2 | メールテンプレートにSchedulerリンク追加 | 30分 | 全接点で予約誘導 |
| P2 | Lark Bot「電話あり」コマンド実装 | 2時間 | 報告習慣化の仕組み |
| P3 | crm_monitor 自動検出（未報告チェック） | 1時間 | Bot併用で報告漏れ完全防止 |
| P3 | 名刺・チラシへの二次元コード追加 | 次回発注時 | オフライン接点からの誘導 |

---

## 7. 次のアクション

1. **即実行**: ララコール2番号目を新eoID（info@tomoshi.jp）で申込
2. **即実行**: Lark SchedulerのURL確認 → tokaiair.com問い合わせページに埋め込み
3. **今週中**: lark_command_executor.py に「電話あり」コマンド追加
4. **今週中**: メールテンプレートのフッターにSchedulerリンク追加

---

Sources:
- [LaLa Call 提供条件](https://lalacall.jp/conditions/)
- [LaLa Call 050番号の複数契約](https://support.lalacall.jp/usqa/service/general/40001617_8176.html)
- [LaLa Call 月額改定のお知らせ](https://support.lalacall.jp/news/1356/)
- [ビジネスLaLa Call 料金](https://business.lalacall.jp/merit/cost/)
- [LaLa Call 申込手順](https://lalacall.jp/procedure/)
