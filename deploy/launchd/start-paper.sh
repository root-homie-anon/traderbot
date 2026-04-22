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
exec "${PROJ}/.venv/bin/python" -m src.main --mode paper
