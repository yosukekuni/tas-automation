#!/usr/bin/env bash
# =============================================================================
# Claude Code Session Watchdog
# =============================================================================
# Monitors the claude CLI process and auto-restarts on session termination
# (plan limits, crashes, etc.) if .auto_queue.md has active: true.
#
# Usage:
#   nohup bash scripts/watchdog.sh &
#
# Stop:
#   kill $(cat scripts/logs/watchdog.pid)
#   or set .auto_queue.md active: false
#
# Future: Replace with launchd plist on Mac mini
# =============================================================================

set -euo pipefail

# --- Configuration ---
WORK_DIR="/mnt/c/Users/USER"
AUTO_QUEUE="${WORK_DIR}/.auto_queue.md"
LOG_FILE="${WORK_DIR}/scripts/logs/watchdog.log"
PID_FILE="${WORK_DIR}/scripts/logs/watchdog.pid"
RESTART_DELAY=30          # seconds to wait before restart
CRASH_WINDOW=300          # 5 minutes: window for crash detection
MAX_CRASHES=3             # max restarts within CRASH_WINDOW
CLAUDE_CMD="claude"
CLAUDE_PROMPT=".auto_queue.mdを読んで前セッションの続きを実行してください。"

# --- State ---
declare -a RESTART_TIMES=()
CHILD_PID=""
MANUAL_STOP=false

# --- Functions ---

log() {
    local timestamp
    timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
    echo "[${timestamp}] $*" | tee -a "${LOG_FILE}"
}

cleanup() {
    MANUAL_STOP=true
    if [[ -n "${CHILD_PID}" ]] && kill -0 "${CHILD_PID}" 2>/dev/null; then
        log "Watchdog stopping. Sending SIGTERM to claude (PID: ${CHILD_PID})"
        kill "${CHILD_PID}" 2>/dev/null || true
    fi
    rm -f "${PID_FILE}"
    log "Watchdog terminated by user (SIGINT/SIGTERM)"
    exit 0
}

trap cleanup SIGINT SIGTERM

check_auto_queue_active() {
    if [[ ! -f "${AUTO_QUEUE}" ]]; then
        log "WARNING: ${AUTO_QUEUE} not found. Treating as inactive."
        return 1
    fi
    if grep -q "^active: true" "${AUTO_QUEUE}"; then
        return 0
    else
        return 1
    fi
}

check_crash_loop() {
    local now
    now="$(date +%s)"
    # Remove timestamps older than CRASH_WINDOW
    local filtered=()
    for t in "${RESTART_TIMES[@]}"; do
        if (( now - t < CRASH_WINDOW )); then
            filtered+=("$t")
        fi
    done
    RESTART_TIMES=("${filtered[@]}")

    if (( ${#RESTART_TIMES[@]} >= MAX_CRASHES )); then
        return 0  # crash loop detected
    fi
    return 1
}

record_restart() {
    RESTART_TIMES+=("$(date +%s)")
}

start_claude() {
    log "Starting claude session..."
    cd "${WORK_DIR}"

    # Run claude in background, capture PID
    ${CLAUDE_CMD} -p "${CLAUDE_PROMPT}" --allowedTools '*' &
    CHILD_PID=$!
    log "Claude started (PID: ${CHILD_PID})"
}

wait_for_claude() {
    local exit_code=0
    wait "${CHILD_PID}" || exit_code=$?
    CHILD_PID=""
    return ${exit_code}
}

# --- Main ---

log "=========================================="
log "Watchdog starting"
log "  Work dir:       ${WORK_DIR}"
log "  Auto queue:     ${AUTO_QUEUE}"
log "  Restart delay:  ${RESTART_DELAY}s"
log "  Crash window:   ${CRASH_WINDOW}s / max ${MAX_CRASHES} restarts"
log "=========================================="

# Write PID file
echo $$ > "${PID_FILE}"
log "Watchdog PID: $$ (saved to ${PID_FILE})"

# Check if claude is already running
EXISTING_PID="$(pgrep -f "claude.*-p" 2>/dev/null | head -1 || true)"
if [[ -n "${EXISTING_PID}" ]]; then
    log "Claude already running (PID: ${EXISTING_PID}). Monitoring existing process."
    CHILD_PID="${EXISTING_PID}"
else
    # Initial check
    if ! check_auto_queue_active; then
        log "auto_queue is not active. Waiting for activation..."
    fi
fi

# Main loop
while true; do
    if [[ "${MANUAL_STOP}" == "true" ]]; then
        break
    fi

    # If no claude process, decide whether to start one
    if [[ -z "${CHILD_PID}" ]] || ! kill -0 "${CHILD_PID}" 2>/dev/null; then
        CHILD_PID=""

        # Check auto_queue
        if ! check_auto_queue_active; then
            log "auto_queue inactive. Sleeping 60s before next check..."
            sleep 60
            continue
        fi

        # Check crash loop
        if check_crash_loop; then
            log "ERROR: Crash loop detected (${MAX_CRASHES} restarts in ${CRASH_WINDOW}s). Halting watchdog."
            log "Manual intervention required. Reset by restarting watchdog."
            rm -f "${PID_FILE}"
            exit 1
        fi

        log "Claude process not running. Waiting ${RESTART_DELAY}s before restart..."
        sleep "${RESTART_DELAY}"

        # Re-check after delay (user might have set active: false)
        if ! check_auto_queue_active; then
            log "auto_queue became inactive during wait. Skipping restart."
            continue
        fi

        record_restart
        start_claude
    fi

    # Wait for claude to exit
    if [[ -n "${CHILD_PID}" ]]; then
        EXIT_CODE=0
        wait_for_claude || EXIT_CODE=$?

        if [[ "${MANUAL_STOP}" == "true" ]]; then
            break
        fi

        log "Claude exited with code: ${EXIT_CODE}"

        case ${EXIT_CODE} in
            0)
                log "Claude exited normally (code 0). Checking if restart needed..."
                ;;
            130)
                log "Claude terminated by SIGINT (Ctrl+C). Not restarting."
                # User intentionally stopped; don't restart
                sleep 60
                ;;
            *)
                log "Claude exited unexpectedly (code ${EXIT_CODE}). Will attempt restart."
                ;;
        esac
    else
        # No process to wait on, poll
        sleep 10
    fi
done

log "Watchdog main loop exited."
rm -f "${PID_FILE}"
