# NAS 個人書類フォルダ構成

**作成日**: 2026-03-17
**NAS**: Synology DS420+ (192.168.0.34)
**共有フォルダ**: 2_area（エリア = 継続的な責任範囲）

---

## フォルダ構成（2_area配下）

```
2_area/
├── HR/                        # 人事・雇用（会社）
│   ├── part_time/             # アルバイト
│   ├── contractors/           # 外部委託
│   ├── contract_docs/         # 契約書
│   ├── in_review/             # 審査中
│   └── rejected/              # 不採用
├── vehicle/                   # 車両（会社/個人混在）
│   └── volvo_xc60/            # ボルボ XC60
├── real_estate/               # 不動産
├── home_maintenance/          # 住宅メンテナンス
├── cashflow/                  # 資金繰り
├── insurance/         [NEW]   # 保険
│   ├── coop_kyosai/           # コープ共済（個人）
│   ├── auto_insurance/        # 自動車保険（東京海上日動）
│   └── life_insurance/        # 生命保険
├── personal_docs/     [NEW]   # 個人書類
│   ├── id_documents/          # 身分証明書（免許・パスポート等）
│   ├── contracts/             # 個人契約（携帯・ネット等）
│   └── certificates/          # 資格証・卒業証書等
├── medical/           [NEW]   # 医療
│   └──（診断書・領収書・健診結果）
├── tax/               [NEW]   # 税務
│   └──（確定申告・年末調整・ふるさと納税）
├── grandma_visit_album/       # おばあちゃん訪問アルバム
└── wishlist/                  # ウィッシュリスト
```

## 今回作成したフォルダ（4カテゴリ+サブ6つ）

| パス | 用途 |
|------|------|
| insurance/ | 保険関連書類の親フォルダ |
| insurance/coop_kyosai/ | コープ共済の証書・請求書類 |
| insurance/auto_insurance/ | 東京海上日動 自動車保険（証券ID515538720） |
| insurance/life_insurance/ | 生命保険 |
| personal_docs/ | 個人書類の親フォルダ |
| personal_docs/id_documents/ | 身分証明書類 |
| personal_docs/contracts/ | 個人契約書類 |
| personal_docs/certificates/ | 資格・証明書 |
| medical/ | 医療（診断書・領収書・健診） |
| tax/ | 税務（確定申告・年末調整） |

## 運用ルール

1. **ScanSnapスキャン** -> `0_inbox/scansnap_inbox/` に一旦格納
2. **仕分け**: 個人/会社で分類し、上記フォルダに移動
3. **命名規則**: `YYYYMMDD_種別_詳細.pdf`（例: `20260317_領収書_歯科治療.pdf`）
4. **保険証書**: 最新版をフォルダ直下に、旧版は `_old/` サブフォルダへ

---

**ステータス**: NASフォルダ作成完了
