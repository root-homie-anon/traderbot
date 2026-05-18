#!/bin/zsh
# start-paper.sh — wrapper that sources .env before launching the bot
# launchd strips the user environment; this ensures OANDA credentials are present.

set -euo pipefail

PROJ="/Users/macmini/projects/traderbot"
ENV_FILE="${PROJ}/.env"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] start-paper.sh starting"

if [[ ! -f "${ENV_FILE}" ]]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: ${ENV_FILE} not found — cannot start" >&2
    exit 1
fi

# Export all vars from .env (skip blank lines and comments)
set -o allexport
# shellcheck source=/dev/null
source "${ENV_FILE}"
set +o allexport

echo "[$(date '+%Y-%m-%d %H:%M:%S')] .env loaded, launching bot..."

# Validation-window config (2026-05-11):
#   - USD-quoted pairs only — isolates the now-correct sizer (JPY/CAD/cross
#     paths only verified by unit tests, not yet in live paper data).
#   - --risk 0.005 (0.5%) — defensive while the cooldown + sizer combo
#     proves out across a clean window of ≥50 trades.
# Restore to defaults (--pairs full set, --risk omitted) once PSR vs 0
# climbs above 50% on the validation window. See ~/dev-vault/projects/traderbot/active-work.md
exec "${PROJ}/.venv/bin/python" -m src.main --mode paper \
    --pairs EUR_USD GBP_USD AUD_USD NZD_USD \
    --risk 0.005
