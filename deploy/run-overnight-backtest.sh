#!/bin/zsh
# run-overnight-backtest.sh — wrapper to kick the backtest pipeline before bed.
#
# Sources .env, activates venv, runs the pipeline, logs to a dated file.
# Safe to run alongside the live paper trader — backtest reads its own
# OHLC CSVs, only touches OANDA for the initial fetch (if missing data).
#
# Usage:
#   ./deploy/run-overnight-backtest.sh             # full run
#   ./deploy/run-overnight-backtest.sh --dry-run   # verify env + data only
#
# Output:
#   ~/dev-vault/projects/traderbot/backtest-results/YYYY-MM-DD/summary.md
#   logs/backtest/overnight-YYYY-MM-DD.log

set -uo pipefail

PROJ="/Users/macmini/projects/traderbot"
ENV_FILE="${PROJ}/.env"
LOG_DIR="${PROJ}/logs/backtest"
LOG_FILE="${LOG_DIR}/overnight-$(date +%Y-%m-%d).log"

mkdir -p "${LOG_DIR}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${LOG_FILE}"; }

log "starting overnight backtest"

if [[ ! -f "${ENV_FILE}" ]]; then
    log "ERROR: ${ENV_FILE} not found — cannot fetch missing OANDA data"
    exit 1
fi

set -o allexport
# shellcheck source=/dev/null
source "${ENV_FILE}"
set +o allexport

log "env loaded; running pipeline (args: $*)"
"${PROJ}/.venv/bin/python" -m src.backtest.overnight "$@" 2>&1 | tee -a "${LOG_FILE}"
EXIT_CODE=${pipestatus[1]:-${PIPESTATUS[0]:-0}}

log "pipeline finished with exit code ${EXIT_CODE}"
log "summary: ~/dev-vault/projects/traderbot/backtest-results/$(date +%Y-%m-%d)/summary.md"
log "log:     ${LOG_FILE}"

exit "${EXIT_CODE}"
