# Claude Code Tasks永続化設計

作成日: 2026-03-14 / ステータス: 凍結（設計書のみ）

## 概要

`CLAUDE_CODE_TASK_LIST_ID` 環境変数を使い、複数セッション間でタスクリストを永続化する。既存のLark Baseタスク管理（tblGrFhJrAyYYWbV）と統合し、唯一のソースを維持する。

## 現状

- タスク管理はLark Base（tblGrFhJrAyYYWbV）に一元化
- セッション起動時にsession-init.shでコンテキスト読み込み
- セッション間のタスク引き継ぎは手動（MEMORYファイル経由）

## 設計

### 環境変数設定

```bash
# .bashrc or session-init.sh
export CLAUDE_CODE_TASK_LIST_ID="lark://base/tblGrFhJrAyYYWbV"
```

### Lark Base統合フロー

```
セッション起動
  ↓
session-init.sh
  ↓
Lark Base API → tblGrFhJrAyYYWbV から未完了タスク取得
  ↓
タスクリストをClaude Codeに注入
  ↓
作業実行
  ↓
タスク完了時 → Lark Base API でステータス更新
```

### 同期スクリプト: sync_tasks.py

```python
# 機能:
# 1. Lark Baseから未完了タスクを取得
# 2. Claude Code用のタスクリスト形式に変換
# 3. タスク完了時にLark Baseを更新
# 4. 会話ログテーブル（tblIyLVn7RFqDbdt）にセッション記録
```

### セッション起動時の自動読み込み

session-init.shに追加:
```bash
# タスク自動読み込み
python3 scripts/sync_tasks.py --load
echo "=== 未完了タスク読み込み完了 ==="
```

## 制約事項

- Lark Baseが唯一のソース（ファイルメモリにタスク一覧を持たない）
- CLAUDE_CODE_TASK_LIST_ID機能はClaude Code本体の対応状況に依存
- 対応前はsync_tasks.pyによる手動同期で代替

## 工数見積もり

| 作業 | 工数 |
|------|------|
| sync_tasks.py作成 | 3時間 |
| session-init.sh改修 | 30分 |
| テスト・調整 | 1時間 |
| **合計** | **4.5時間** |

## 優先順位

**低**: Claude Code本体のタスクリスト永続化機能の正式リリースを待つ。それまではLark Base + session-init.shの現行運用で十分。
