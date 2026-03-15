#!/bin/bash
# claude_watchdog.sh
# Claude Codeプロセスを監視し、停止+auto_queue.md active時に自動再起動
#
# 使い方:
#   chmod +x claude_watchdog.sh
#   nohup ./claude_watchdog.sh &
#   # または: screen -S watchdog -d -m ./claude_watchdog.sh
#
# 停止:
#   kill $(cat /tmp/claude_watchdog.pid)
#   # または: touch /tmp/claude_watchdog_stop

QUEUE_FILE="/mnt/c/Users/USER/Documents/_data/tas-automation/.auto_queue.md"
LOG_FILE="/mnt/c/Users/USER/Documents/_data/tas-automation/logs/watchdog.log"
PID_FILE="/tmp/claude_watchdog.pid"
STOP_FILE="/tmp/claude_watchdog_stop"
CHECK_INTERVAL=300  # 5分ごとにチェック
RESTART_COOLDOWN=600  # 再起動後10分はチェックしない（制限リセット待ち）

# ログディレクトリ作成
mkdir -p "$(dirname "$LOG_FILE")"

# PIDファイル作成
echo $$ > "$PID_FILE"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

cleanup() {
    log "Watchdog停止"
    rm -f "$PID_FILE" "$STOP_FILE"
    exit 0
}

trap cleanup SIGINT SIGTERM

log "Watchdog起動 (PID: $$, チェック間隔: ${CHECK_INTERVAL}秒)"

while true; do
    # 停止ファイルチェック
    if [ -f "$STOP_FILE" ]; then
        log "停止ファイル検出。Watchdog終了"
        cleanup
    fi

    # auto_queue.mdの存在確認
    if [ ! -f "$QUEUE_FILE" ]; then
        log "auto_queue.md不在。スキップ"
        sleep "$CHECK_INTERVAL"
        continue
    fi

    # active: true かチェック
    if ! grep -q "^active: true" "$QUEUE_FILE"; then
        log "auto_queue: inactive。スキップ"
        sleep "$CHECK_INTERVAL"
        continue
    fi

    # stop_at時刻チェック（設定されている場合）
    STOP_AT=$(grep "^stop_at:" "$QUEUE_FILE" | head -1 | awk '{print $2}')
    if [ -n "$STOP_AT" ] && [ "$STOP_AT" != "user_message" ]; then
        STOP_EPOCH=$(date -d "$STOP_AT" +%s 2>/dev/null)
        NOW_EPOCH=$(date +%s)
        if [ -n "$STOP_EPOCH" ] && [ "$NOW_EPOCH" -ge "$STOP_EPOCH" ]; then
            log "stop_at時刻 ($STOP_AT) を超過。auto_queueをinactiveに更新"
            sed -i 's/^active: true/active: false/' "$QUEUE_FILE"
            sleep "$CHECK_INTERVAL"
            continue
        fi
    fi

    # remaining_tasksが空かチェック
    REMAINING=$(grep -A 100 "^remaining_tasks:" "$QUEUE_FILE" | grep -c "^\s*- ")
    if [ "$REMAINING" -eq 0 ]; then
        log "残タスクなし。auto_queueをinactiveに更新"
        sed -i 's/^active: true/active: false/' "$QUEUE_FILE"
        sleep "$CHECK_INTERVAL"
        continue
    fi

    # Claude Codeプロセスが生きてるか確認
    if pgrep -f "claude" > /dev/null 2>&1; then
        log "Claude Code稼働中 (残タスク: $REMAINING件)。監視継続"
        sleep "$CHECK_INTERVAL"
        continue
    fi

    # Claude Codeが停止 + auto_queue active + 残タスクあり → 再起動
    log "⚠️ Claude Code停止検出！残タスク${REMAINING}件あり。再起動します"

    # 再起動プロンプト
    PROMPT="自律継続モードです。/mnt/c/Users/USER/Documents/_data/tas-automation/.auto_queue.md を読んで、remaining_tasksから次のバッチを起動してください。前セッションが制限到達またはクラッシュで停止しました。"

    # Claude Code headless実行
    log "claude -p 実行中..."
    claude -p "$PROMPT" >> "$LOG_FILE" 2>&1 &
    CLAUDE_PID=$!
    log "Claude Code再起動 (PID: $CLAUDE_PID)"

    # クールダウン（制限リセット待ち）
    log "クールダウン ${RESTART_COOLDOWN}秒"
    sleep "$RESTART_COOLDOWN"
done
