"""CLI entry point — download historical candle data for all active pairs.

Usage:
    set -a && source .env && set +a
    python3 -m src.data.run_fetch

Optional overrides via environment variables:
    FETCH_PAIRS      space-separated list  (default: the 5 active pairs)
    FETCH_TIMEFRAMES space-separated list  (default: H1)
    FETCH_COUNT      integer               (default: 5000)
    FETCH_OUTPUT_DIR path                  (default: data/historical)
"""

import logging
import os
import sys
from pathlib import Path

from src.broker.oanda_connector import OandaConnector
from src.data.historical_fetcher import HistoricalFetcher, HistoricalFetchError
from src.logger import setup_logger

setup_logger()
logger = logging.getLogger("pa_bot")

DEFAULT_PAIRS = ["EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD"]
DEFAULT_TIMEFRAMES = ["H1"]
DEFAULT_COUNT = 5000
DEFAULT_OUTPUT_DIR = str(Path(__file__).resolve().parent.parent.parent / "data" / "historical")


def _parse_env_list(key: str, default: list[str]) -> list[str]:
    raw = os.environ.get(key, "").strip()
    return raw.split() if raw else default


def main() -> int:
    pairs = _parse_env_list("FETCH_PAIRS", DEFAULT_PAIRS)
    timeframes = _parse_env_list("FETCH_TIMEFRAMES", DEFAULT_TIMEFRAMES)

    try:
        count = int(os.environ.get("FETCH_COUNT", DEFAULT_COUNT))
    except ValueError:
        logger.error("FETCH_COUNT must be an integer")
        return 1

    output_dir = os.environ.get("FETCH_OUTPUT_DIR", DEFAULT_OUTPUT_DIR)

    print(f"Pairs      : {' '.join(pairs)}")
    print(f"Timeframes : {' '.join(timeframes)}")
    print(f"Count      : {count} candles per request")
    print(f"Output     : {output_dir}")
    print()

    connector = OandaConnector()
    if not connector.connect():
        logger.error("Could not connect to OANDA — check OANDA_API_KEY and OANDA_ACCOUNT_ID")
        return 1

    fetcher = HistoricalFetcher(connector)

    try:
        results = fetcher.fetch_all_pairs(
            pairs=pairs,
            timeframes=timeframes,
            count=count,
            output_dir=output_dir,
        )
    finally:
        connector.disconnect()

    # Report results
    print()
    successes = 0
    failures = 0
    for key, outcome in results.items():
        if isinstance(outcome, Exception):
            print(f"  FAIL  {key}: {outcome}")
            failures += 1
        else:
            print(f"  OK    {key} -> {outcome}")
            successes += 1

    print()
    print(f"Done: {successes} succeeded, {failures} failed")

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
