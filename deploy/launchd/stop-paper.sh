#!/bin/zsh
# stop-paper.sh — Friday 17:00 shutdown for com.traderbot.paper
#
# Strategy: send SIGTERM to the bot and wait for it to exit cleanly (exit 0).
# The bot's signal handler sets _running=False; it exits after the current 120s cycle.
# KeepAlive: { SuccessfulExit: false } means launchd will NOT restart on exit 0.
# The job stays registered in launchd's registry and will fire again on the next
# Sunday 17:00 StartCalendarInterval trigger — no bootout/bootstrap needed.
#
# NOTE: Do NOT use bootout/bootstrap here. Re-bootstrapping a job clears launchd's
# throttle state, which can cause it to start immediately even with RunAtLoad=false.
# The clean-exit path is the correct and sufficient stop mechanism.

set -uo pipefail

LABEL="com.traderbot.paper"
UID_VAL=$(id -u)

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

log "stop-paper.sh starting"

# Find the bot's PID
BOT_PID=$(pgrep -f "python.*-m src.main" 2>/dev/null || true)

if [[ -z "${BOT_PID}" ]]; then
    log "no running bot process found — nothing to stop"
    log "stop-paper.sh done — job idle, scheduled for next Sunday 17:00"
    exit 0
fi

log "sending SIGTERM to PID ${BOT_PID} — waiting for clean exit (max 180s)"
kill -TERM "${BOT_PID}" 2>/dev/null || true

WAITED=0
while kill -0 "${BOT_PID}" 2>/dev/null; do
    if (( WAITED >= 180 )); then
        log "WARNING: bot did not exit within ${WAITED}s — sending SIGKILL" >&2
        log "WARNING: SIGKILL will cause a non-zero exit and KeepAlive may restart the bot" >&2
        log "WARNING: if bot restarts, re-run this script to stop it cleanly" >&2
        kill -KILL "${BOT_PID}" 2>/dev/null || true
        sleep 3
        break
    fi
    sleep 5
    (( WAITED += 5 )) || true
done

if ! kill -0 "${BOT_PID}" 2>/dev/null; then
    log "bot exited cleanly after ${WAITED}s — KeepAlive will not restart (exit 0)"
    log "job remains registered and will fire next Sunday 17:00"
else
    log "ERROR: process still running after SIGKILL — manual intervention may be required" >&2
    exit 1
fi

log "stop-paper.sh done"
