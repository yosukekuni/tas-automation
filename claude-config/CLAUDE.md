# TOMOSHI Site - Project Instructions

## 必須ルール（全セッション共通）

### 1. セッション開始時
- Lark Base タスク管理テーブル（tblGrFhJrAyYYWbV / Base: HSSMb3T2jalcuysFCjGjJ76wpKe）の**未完了タスク**を取得して一覧表示する
- ユーザーに「今日は何から？」と聞く前に、まず積み残しを把握する

### 2. タスク投入
- ユーザーの依頼・「メモリしておいて」は**即座に**Lark Baseタスクテーブルに投入する
- 会話中に発生した新タスク（自分で気づいたものも含む）も投入する
- 投入時フィールド: タスク名, プロジェクト(TAS/TOMOSHI/個人), 優先度(高/中/低), ステータス, 備考, オーダー元
- ※オーダー日は書き込まない（Lark Baseの「作成日時」自動フィールドを使用）

### 3. セッション終了時
- 完了したタスクのステータスを「完了」+完了日に更新する
- 未完了タスクは次セッションで自動的に引き継がれる

### 4. Lark Base API接続情報
- automation_config.json: /mnt/c/Users/USER/Documents/_data/automation_config.json
- タスク管理Base: HSSMb3T2jalcuysFCjGjJ76wpKe
- タスクテーブル: tblGrFhJrAyYYWbV
- 会話ログテーブル: tblIyLVn7RFqDbdt

### 5. ブランド分離
- TOMOSHI（灯し）とTAS（東海エアサービス）は完全に分離。混ぜない。
- TOMOSHIの連絡はtomoshi.jpメールから。TASの連絡はtokaiair.comから。
