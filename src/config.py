"""Load configuration from config.json or environment variables."""

import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"

# Risk Management
RISK_PER_TRADE = 0.01       # 1% of account
MAX_DAILY_LOSS = 0.10       # 10% of account
MAX_POSITIONS = None        # Unlimited within risk

# Entry Rules
CONFLUENCE_MIN = 2          # Min confluence factors required (0-6)
TREND_STRENGTH_MIN = 40     # Minimum trend strength (0-100)
QUALITY_SCORE_MIN = 55      # Minimum quality score (0-100)

# Pair Selection
TOP_PAIRS = 9               # Trade top 9 pairs
AUTO_PAIR_SELECTION = True   # Dynamic pair selection

# Broker
BROKER = "OANDA"            # OANDA or BINANCE
TRADING_MODE = "paper"      # "paper" or "live"

# Timeframes
TIMEFRAMES = ["M15", "H1", "H4", "D"]


def load_config(path=None):
    """Load config from JSON file, falling back to defaults above."""
    config_path = path or DATA_DIR / "config.json"
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)
    return {}
