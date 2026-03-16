# freee連携自動化 レビュー & フロー設計

生成日: 2026-03-16
対象: 受注 -> 請求 -> 入金 完全フロー

---

## 1. 現状の構成

### 既存スクリプト一覧

| スクリプト | 機能 | 状態 |
|-----------|------|------|
| `freee_invoice_creator.py` | CRM受注台帳 -> freee請求書自動生成 | 稼働可 |
| `freee_pl_generator.py` | freee月次P&L取得 + 未入金請求書一覧 | 稼働可 |
| `freee_site_name_updater.py` | freee請求書の現場名 -> CRM受注台帳反映 | 完了済（24件更新済） |
| `crm_order_sync.py` | 受注台帳-商談ファジーマッチング | 稼働可 |

### データフロー（現状）

```
[CRM受注台帳] ──(手動入力)──> 請求金額 + 請求日
       │
       ├── freee_invoice_creator.py ──> [freee請求書作成]
       │    条件: 請求金額あり + 請求日あり + 入金日なし
       │    重複チェック: partner_id + 金額で既存freee請求書と照合
       │
       ├── freee_pl_generator.py ──> [月次P&L] + [未入金一覧]
       │
       └── freee_site_name_updater.py ──> [案件名正規化]（完了済）
```

### freee API情報

- company_id: 2259197
- template_id: 1302995（三井住友銀行・インボイス番号含む）
- 請求書API: `/iv/invoices`（POST=作成, GET=一覧取得）
- 会計API: `/api/1/`（試算表、取引先、請求書取得）
- 最新請求書番号: INV-0000000060
- 取引先マッピング: PARTNER_MAP に72社登録済み

---

## 2. 受注 -> 請求 -> 入金 完全フロー設計

### Phase A: 受注確定（CRM更新）

```
トリガー: 受注確定時（手動 or crm_order_sync.py）
  1. 受注台帳に新規レコード追加（案件名・取引先・受注金額）
  2. 商談ステージを「受注」に更新
  3. 取引先がPARTNER_MAPに未登録の場合 → 警告ログ出力
```

### Phase B: 請求書作成

```
トリガー: 請求日入力時（手動入力が起点）
  1. freee_invoice_creator.py --check-only で対象確認
  2. freee_invoice_creator.py --execute で請求書作成
  3. 作成結果をログ保存（backups/yyyymmdd_invoice_create_log.json）
```

### Phase C: 入金確認 & 消込（現状は手動）

```
トリガー: freee上の入金確認
  1. freeeで入金消込（手動）
  2. CRM受注台帳の「入金日」に日付入力（手動）
  → 自動化ギャップ: ここが手動のまま
```

---

## 3. 品質評価

### freee_invoice_creator.py の評価

**良い点:**
- dry-run/check-only/executeの3モード対応
- 重複チェック（partner_id + 金額で既存請求書と照合）
- バックアップ自動保存
- PARTNER_MAP に72社登録済みで大半の取引先をカバー
- 支払期限の自動計算（末締め翌15日）
- Larkタイムスタンプの正しいハンドリング

**改善すべき点:**

| # | 課題 | 重要度 | 対応 |
|---|------|--------|------|
| 1 | CONFIG_FILEのパスが `/mnt/c/Users/USER/Documents/_data/automation_config.json` 固定 | 中 | 環境変数 or フォールバック追加 |
| 2 | 重複チェックが金額一致のみ（同一取引先に同額の別案件がある場合に誤判定） | 高 | 案件名・請求日も加味した重複チェック |
| 3 | CRM受注台帳へのfreee請求書番号の書き戻しがない | 高 | 作成後にLark更新 |
| 4 | 入金確認の自動化がない | 高 | freee入金ステータス監視 -> CRM更新 |
| 5 | GitHub Actions workflowが未設定 | 中 | 定期実行の自動化 |
| 6 | 取引先未登録時の通知がコンソール出力のみ | 中 | Lark Webhook通知追加 |
| 7 | 請求日が過去の場合の警告がない | 低 | バリデーション追加 |

### freee_pl_generator.py の評価

**良い点:**
- 累計差分方式で正確な月次P&L計算
- 会計年度ロジックの正しい実装
- 未入金請求書一覧取得機能
- JSON出力 + コンソールサマリーの2系統出力

**改善すべき点:**
- 未入金請求書の取得APIが `/api/1/invoices`（会計API）だが、請求書作成は `/iv/invoices`（iv API）を使っており、APIの一貫性がない（ただし機能的には正しい）

---

## 4. 実装した改善

### 改善1: 重複チェックの強化

現状の重複チェックは `partner_id + 金額` のみ。同一取引先に同額案件がある場合に誤判定する。

**対策:** 請求日（billing_date）も加味。同一取引先 + 同額 + 請求日が30日以内 = 重複と判定。

### 改善2: freee請求書番号のCRM書き戻し

請求書作成後にCRM受注台帳の「備考」フィールドにfreee請求書番号を記録する機能を追加。
これにより:
- どの受注台帳レコードが請求済みか一目でわかる
- 二重請求防止の追加レイヤー

### 改善3: 入金確認自動化スクリプト

`freee_payment_checker.py` を新規作成:
- freee iv APIから請求書のpayment_statusを監視
- 「入金済み」になった請求書をCRM受注台帳の「入金日」に反映
- Lark Webhook通知

### 改善4: 取引先未登録の自動検出 & 通知

未登録取引先を検出した場合にLark Webhook通知を送信。

---

## 5. 完全自動化フロー（目標状態）

```
[CRM受注台帳]
    │
    ├─ 請求金額 + 請求日入力（手動トリガー）
    │
    ▼
[freee_invoice_creator.py] ── 定期実行（GitHub Actions）
    │  ・未請求案件を自動検出
    │  ・重複チェック（partner_id + 金額 + 請求日）
    │  ・freee請求書作成
    │  ・CRM受注台帳にfreee請求書番号を書き戻し
    │  ・取引先未登録時はLark Webhook通知
    │
    ▼
[freee_payment_checker.py] ── 定期実行（GitHub Actions）
    │  ・freee請求書のpayment_statusを監視
    │  ・入金確認時にCRM受注台帳の「入金日」を自動更新
    │  ・Lark Webhook通知（入金完了 or 支払期限超過）
    │
    ▼
[freee_pl_generator.py] ── 月次実行
    │  ・月次P&L取得
    │  ・未入金一覧取得
    │
    ▼
[朝ブリーフィング] ── daily_briefing.py に統合
       ・未請求案件数
       ・未入金請求書一覧
       ・支払期限超過アラート
```

---

## 6. 受注台帳フィールドマッピング

| CRMフィールド | 用途 | 請求書作成での扱い |
|--------------|------|-------------------|
| 案件名 | 請求書の件名（subject）+ 明細の品名 | 先頭50文字をsubjectに |
| 取引先 | freee partner_idの特定 | PARTNER_MAPで名寄せ |
| 受注金額 | 請求金額が未入力時のフォールバック | invoice_amountが優先 |
| 請求金額 | 請求書の金額 | unit_priceに設定 |
| 請求日 | 請求書のbilling_date | そのまま使用 |
| 入金日 | 入金済み判定 | 入力済み=スキップ |
| サービス種別 | 明細の品名フォールバック | case_nameが空の場合 |

---

## 7. PARTNER_MAP管理

現在72社登録済み。新規取引先の追加フロー:

1. freee_invoice_creator.py 実行時に「取引先不明」で検出
2. freee管理画面で取引先を新規登録 -> partner_idを取得
3. PARTNER_MAPにエントリ追加

**自動化候補:** freee `/api/1/partners` APIで取引先一覧を取得し、PARTNER_MAPとの差分を自動検出。ただし現状の72社カバーで十分で、新規取引先は月1-2社程度のため、手動管理で問題ない。

---

## 8. 支払条件

- 標準: 末締め翌15日払い
- 計算ロジック: `calc_payment_date()` で自動計算
  - 例: 3月請求 -> 4月15日期限
  - 12月請求 -> 翌年1月15日期限
- 特殊条件の取引先は現状なし（全社統一条件）

---

## 9. リスク & 注意事項

| リスク | 影響 | 対策 |
|-------|------|------|
| freee APIトークン期限切れ | 請求書作成失敗 | 自動リフレッシュ実装済み（401時にrefresh） |
| 同一取引先に同額案件 | 重複請求の誤判定 | 請求日も加味した重複チェックに改善 |
| PARTNER_MAP未登録の新規取引先 | 請求書作成スキップ | Lark Webhook通知で即座に把握 |
| CRM受注台帳の請求金額が税込/税抜混在 | 金額不一致 | freee側はtax_entry_method="out"（税抜入力）で統一 |
| Lark APIレート制限 | 大量更新時に失敗 | sleep(0.3)で対応済み |

---

## 10. 次のアクション

### 即時対応（本セッション）
- [x] 既存スクリプトの全体レビュー完了
- [x] フロー設計ドキュメント作成
- [x] freee_invoice_creator.py の改善（重複チェック強化 + CRM書き戻し）
- [x] freee_payment_checker.py 新規作成（入金確認自動化）

### 次回対応（優先度順）
1. GitHub Actions workflow作成（freee_invoice_check.yml）-- 毎日9時に--check-only実行
2. freee_payment_checker.pyのGitHub Actions化
3. daily_briefing.pyへの未請求/未入金サマリー統合
4. PARTNER_MAP自動更新スクリプト（低優先度）
