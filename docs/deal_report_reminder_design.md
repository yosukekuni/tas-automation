# 電話着信後 商談報告リマインド 設計書

作成日: 2026-03-14
ステータス: 設計完了・実装待ち
関連: [phone_operation_design.md](phone_operation_design.md) Phase 2 / [deal_stage_flow_design.md](deal_stage_flow_design.md)

---

## 1. 目的

電話着信後30分以内に商談報告フォーム（CRM商談テーブル）に入力がない場合、Lark Botでリマインドを送信する。
営業の報告漏れを防ぎ、CRMデータの完全性を担保する。

---

## 2. 制約事項

| 制約 | 影響 | 対策 |
|------|------|------|
| ララコールに着信履歴APIがない | 着信を自動検知できない | Lark Botコマンド「電話あり」で手動記録 |
| GitHub Actionsは15分間隔実行 | 正確な30分タイマー不可 | state JSONに記録時刻保存 → 次回実行時に経過チェック（実質15-30分後にリマインド） |
| 政木はLark DM不可（外部委託） | Bot DMが届かない | メール送信で代替（既存 send_email_notification） |

---

## 3. 全体フロー

```
[電話着信 → 通話終了]
  ↓
[ユーザーがLark DMで「電話あり 会社名」と送信]
  ↓
[lark_command_executor.py が受信]
  ├─ phone_call_state.json に記録: {会社名, 記録時刻, 記録者open_id}
  ├─ Lark DM返信: 「了解。30分後に商談報告チェックします。→ 報告フォーム: [URL]」
  └─ 即座にフォームURLを提示（入力促進）
  ↓
[crm_monitor.py 15分毎実行]
  ↓
[check_phone_report_missing() が呼ばれる]
  ├─ phone_call_state.json を読み込み
  ├─ 記録時刻から30分以上経過したエントリを抽出
  ├─ 商談テーブル(tbl1rM86nAw9l3bP)を検索:
  │   「記録時刻以降に作成された、同一会社名を含む商談レコード」があるか？
  ├─ YES → 報告済み。stateから削除。完了。
  └─ NO  → リマインド送信
              ├─ 1回目（30分経過）: 担当者にLark DM / メール
              ├─ 2回目（60分経過）: 担当者 + CEOにLark DM
              └─ 3回目以降: 送信しない（翌日の日次サマリーに集約）
```

---

## 4. コンポーネント設計

### 4.1 phone_call_state.json（新規ファイル）

パス: `scripts/phone_call_state.json`

```json
{
  "pending_calls": [
    {
      "id": "call_20260314_153000",
      "company": "和合コンサルタント",
      "recorded_at": "2026-03-14T15:30:00",
      "recorded_by": "ou_d2e2e520a442224ea9d987c6186341ce",
      "reminder_count": 0,
      "resolved": false
    }
  ],
  "resolved_today": [
    {
      "id": "call_20260314_100000",
      "company": "ABC建設",
      "resolved_at": "2026-03-14T10:20:00",
      "resolved_by": "report_found"
    }
  ]
}
```

フィールド説明:
- `id`: `call_{日付}_{時刻}` 形式のユニークID
- `company`: 会社名（部分一致検索に使用）
- `recorded_at`: 電話記録時刻（ISO 8601）
- `recorded_by`: 記録者のLark open_id
- `reminder_count`: リマインド送信回数（0=未送信, 1=30分後, 2=60分後）
- `resolved`: 報告確認済みフラグ

ライフサイクル:
- `pending_calls`: 未解決の電話記録。報告確認後 `resolved_today` に移動。
- `resolved_today`: 当日中の解決済み記録。翌日のcrm_monitor初回実行時にクリア。
- 48時間経過した未解決エントリは自動で `expired` として除去（無限蓄積防止）。

### 4.2 lark_command_executor.py への追加

#### コマンド定義

```
コマンド: 電話あり [会社名]
エイリアス: tel [会社名] / 電話 [会社名]
```

#### 処理フロー

1. メッセージから会社名を抽出（「電話あり」以降のテキスト）
2. 会社名が空の場合 → 「会社名を入力してください（例: 電話あり 和合コンサルタント）」と返信
3. `phone_call_state.json` に新規エントリ追加
4. Lark DM返信:
   ```
   了解。「和合コンサルタント」の電話を記録しました。
   30分後に商談報告チェックします。

   → 報告フォーム: https://ejpe1b5l3u3p.jp.larksuite.com/share/base/{FORM_VIEW_URL}
   ```

#### 入力バリエーション対応

| 入力例 | 解釈 |
|--------|------|
| `電話あり 和合コンサルタント` | company = "和合コンサルタント" |
| `tel ABC建設` | company = "ABC建設" |
| `電話 山田太郎（個人名）` | company = "山田太郎" |
| `電話あり` | → エラー返信: 会社名を入力してください |

### 4.3 lark_crm_monitor.py への追加関数

#### check_phone_report_missing()

既存の `main()` デフォルト実行フローに追加。15分毎に呼ばれる。

```
処理フロー:
1. phone_call_state.json を読み込み
2. pending_calls が空なら即 return（API呼び出し節約）
3. 各 pending_call について:
   a. 経過時間 = now - recorded_at
   b. 経過時間 < 30分 → スキップ（まだ猶予期間内）
   c. 商談テーブルから recorded_at 以降に作成されたレコードを検索
      - 検索条件: 商談名 or 取引先名に company が部分一致
      - 該当レコードあり → resolved=true, resolved_today に移動
   d. 該当レコードなし & reminder_count == 0:
      → 1回目リマインド（担当者のみ）
      → reminder_count = 1
   e. 該当レコードなし & reminder_count == 1 & 経過 >= 60分:
      → 2回目リマインド（担当者 + CEO）
      → reminder_count = 2
   f. reminder_count >= 2:
      → これ以上送信しない
4. 48時間超過の pending_call を自動除去
5. resolved_today の日付が古いエントリをクリア
6. state保存
```

#### 商談レコード検索ロジック（報告済み判定）

```
検索対象: 商談テーブル tbl1rM86nAw9l3bP の全レコード（fetch_all_deals()の結果を共用）

判定条件（OR）:
  1. 商談名に company を含む & 商談日 >= recorded_at
  2. 取引先リンクのテキストに company を含む & 商談日 >= recorded_at
  3. 新規取引先名に company を含む & 商談日 >= recorded_at

一致しない場合でも、recorded_at 以降に作成された商談レコードが1件以上あれば
「別名で登録された可能性」としてログ出力（リマインドは送信する）
```

注意: fetch_all_deals() は既にデフォルト実行フローの他チェック（check_overdue_actions等）で呼ばれている。API呼び出し回数を増やさないよう、main()レベルで1回取得して引数として渡す設計にする（既存のcheck_stage_transitionsと同じパターン）。

#### リマインドメッセージ

**1回目（30分経過）**:
```
商談報告リマインド
「{会社名}」との電話から30分経過しました。
商談報告をお願いします。

→ 報告フォーム: {FORM_URL}
```

**2回目（60分経過）**:
```
商談報告リマインド（2回目）
「{会社名}」との電話から60分以上経過。報告未入力です。

→ 報告フォーム: {FORM_URL}
→ 入力が不要な場合は「報告不要 {会社名}」と送信してください。
```

#### 「報告不要」コマンド（lark_command_executor.py）

営業判断で報告が不要な電話（間違い電話、既存顧客からの事務連絡等）の場合にリマインドを停止する手段。

```
コマンド: 報告不要 [会社名]
処理: pending_calls から該当エントリを resolved_today に移動（resolved_by = "manual_skip"）
返信: 「{会社名}の商談報告リマインドを解除しました。」
```

### 4.4 main() への組み込み位置

```python
# lark_crm_monitor.py main() のデフォルト実行フロー

def main():
    ...
    # 既存チェック
    check_for_new_records()
    check_overdue_actions()
    check_hot_warm_no_action()
    check_new_deal_missing_fields()
    check_stage_transitions()

    # 新規追加（全時間帯で実行 — 電話は営業時間中いつでもかかる）
    check_phone_report_missing()    # ← ここに追加
    ...
```

CLIオプション追加:
```
--phone-check    電話報告チェックのみ実行
```

---

## 5. crm_monitor_state.json との関係

phone_call_state.json は crm_monitor_state.json とは別ファイルとする。

理由:
- crm_monitor_state.json はレコードカウント・スナップショットなど「CRM状態」を管理
- phone_call_state.json は「電話記録キュー」であり、ライフサイクルが異なる（エントリが追加・消化される）
- 別ファイルにすることで、一方の破損が他方に影響しない

---

## 6. 通知先ルーティング

| 記録者 | 1回目リマインド先 | 2回目リマインド先 |
|--------|------------------|------------------|
| 國本（CEO） | CEO自身にLark DM | CEO自身にLark DM（エスカレーション不要） |
| 新美 | 新美にLark DM (open_id) | 新美 + CEO |
| 政木 | 政木にメール | 政木にメール + CEO Lark DM |

記録者の特定:
- lark_command_executor.py は `LARK_COMMAND_SENDER`（open_id）を受け取る
- open_id → SALES_REPS マッピングで担当者名を逆引き
- マッチしない場合はCEOとみなす（國本のopen_idか、未登録ユーザー）

---

## 7. API呼び出しの最適化

| 操作 | API呼び出し | 頻度 |
|------|------------|------|
| phone_call_state.json 読み込み | なし（ローカルファイル） | 毎回 |
| 商談テーブル全件取得 | Lark Bitable API | 既存の fetch_all_deals() を共用（追加呼び出しゼロ） |
| リマインド送信 | Lark Bot Message API | 未報告時のみ（1-2回/件） |

pending_calls が空の場合、API呼び出しは一切発生しない。

---

## 8. エッジケース対応

| ケース | 挙動 |
|--------|------|
| 同一会社から短時間に2回着信 | 2エントリ作成。どちらか1件の報告で両方 resolved にはしない（各通話ごとに報告が必要） |
| 会社名の表記ゆれ（例: 「和合」vs「和合コンサルタント」） | 部分一致検索で対応。「和合」で記録 → 商談名に「和合コンサルタント」があれば一致 |
| GitHub Actionsが一時停止（メンテナンス等） | state JSONに記録済みのため、復帰後に遅延リマインドが発動。48時間超過エントリは自動除去 |
| crm_monitor実行中にlark_command_executorが同時書き込み | GitHub Actionsではワークフロー実行が直列のため競合しない。ローカル実行時のみリスクあり（許容） |
| 営業時間外の電話記録 | 時間帯制限なし。深夜に記録しても30分後チェックは通常通り動作 |
| 商談報告は入力したが会社名が異なる | 未検出 → リマインド送信。「報告不要」コマンドで解除 |

---

## 9. 商談報告フォームの準備

既存の商談テーブル（tbl1rM86nAw9l3bP）のフォームビュー（vew6ijuGYp）を使用。

フォームに追加が必要なフィールド:
- **接触チャネル**（単一選択）: 選択肢に「電話（着信）」「電話（発信）」を追加
  - 既存選択肢: 訪問 / Web問い合わせ / メール / 紹介 等
  - 電話報告時にこの値を設定することで、後続の分析（電話経由の商談件数・受注率）が可能

フォームURL定数:
```
DEAL_REPORT_FORM_URL = "https://ejpe1b5l3u3p.jp.larksuite.com/share/base/form/shrlgXXXXXXXX"
```
※ 実際のフォーム共有URLはLark Base管理画面から取得

---

## 10. 実装優先順位

| 順序 | 内容 | 工数 | 依存 |
|-----|------|------|------|
| 1 | CRM商談テーブルに「接触チャネル」フィールド追加 + フォームURL取得 | 15分 | なし（Lark Base管理画面で手動操作） |
| 2 | phone_call_state.json の読み書きユーティリティ | 30分 | なし |
| 3 | lark_command_executor.py に「電話あり」「報告不要」コマンド追加 | 1時間 | #2 |
| 4 | lark_crm_monitor.py に check_phone_report_missing() 追加 | 1.5時間 | #2 |
| 5 | main() への組み込み + --phone-check オプション | 15分 | #4 |
| 6 | --dry-run でのテスト実行 | 30分 | #3, #4, #5 |

合計: 約4時間

---

## 11. テスト計画

1. **ユニットテスト（--dry-run）**
   - phone_call_state.json にテストエントリを手動作成
   - `python3 lark_crm_monitor.py --phone-check --dry-run` で検出・メッセージ生成を確認
   - 商談テーブルにテストレコード作成 → resolved判定の動作確認

2. **統合テスト**
   - Lark DMで「電話あり テスト会社」を送信
   - 30分待機（または15分後のcrm_monitor実行を待つ）
   - リマインドDMが届くことを確認
   - CRMにテスト商談を入力 → 次回実行でresolvedになることを確認

3. **エッジケーステスト**
   - 「報告不要 テスト会社」でリマインド停止確認
   - 48時間超過エントリの自動除去確認
   - 2回目リマインド（60分後）のCEOエスカレーション確認

4. **テストデータ削除**
   - テスト商談レコード削除
   - phone_call_state.json のテストエントリ削除

---

## 12. 将来拡張

- **自動検出方式の追加**: 「接触チャネル=電話」かつ「ヒアリング内容=空」のレコードを定期検出 → Botコマンドなしでもリマインド（Phase 2で検討）
- **通話時間の記録**: 将来的にIP電話APIが利用可能になった場合、通話時間も記録して短時間通話（< 1分）はリマインド対象外にする
- **音声文字起こし連携**: 録音ファイルの自動文字起こし結果をヒアリング内容に自動転記（既存の録音文字起こしパイプラインと統合）
- **日次未報告サマリー**: 朝8時の実行時に、前日の未報告件数をCEOに通知（check_action_remindersの拡張）
