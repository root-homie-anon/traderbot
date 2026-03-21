"""Fetch and persist historical OHLCV candle data from OANDA."""

import logging
import time
from pathlib import Path

import pandas as pd

from src.broker.oanda_connector import OandaConnector

logger = logging.getLogger("pa_bot")


class HistoricalFetchError(Exception):
    """Raised when a candle fetch fails after exhausting retries."""


class HistoricalFetcher:
    """Downloads OANDA candle history and saves it to CSV for backtesting.

    Uses OandaConnector.get_candles() as the transport layer — no direct
    HTTP calls here, keeping the API surface in one place.

    Data contract out:
        DataFrame with DatetimeIndex (tz-naive UTC) and columns:
            open (float), high (float), low (float), close (float), volume (int)
        Saved CSV has the same shape; first column is the timestamp index.
    """

    def __init__(self, connector: OandaConnector) -> None:
        self._connector = connector

    def fetch_candles(
        self,
        pair: str,
        timeframe: str,
        count: int = 5000,
    ) -> pd.DataFrame:
        """Fetch up to *count* completed candles for *pair* / *timeframe*.

        Delegates to OandaConnector.get_candles which handles:
          - granularity mapping
          - mid-price extraction (candles[].mid.o/h/l/c)
          - incomplete candle filtering
          - DatetimeIndex construction (tz stripped to naive UTC)

        Args:
            pair: OANDA instrument name, e.g. "EUR_USD"
            timeframe: OANDA granularity code, e.g. "H1", "M15"
            count: number of candles to request (OANDA hard cap: 5000)

        Returns:
            DataFrame with DatetimeIndex and columns open/high/low/close/volume.
            Empty DataFrame if OANDA returns no completed candles.

        Raises:
            HistoricalFetchError: if the API call fails.
        """
        clamped = min(count, 5000)
        logger.info("Fetching %d %s %s candles from OANDA", clamped, pair, timeframe)

        try:
            df = self._connector.get_candles(pair, timeframe, count=clamped)
        except Exception as exc:
            raise HistoricalFetchError(
                f"Failed to fetch {pair} {timeframe}: {exc}"
            ) from exc

        if df.empty:
            logger.warning("No completed candles returned for %s %s", pair, timeframe)
        else:
            logger.info(
                "Received %d candles for %s %s  [%s → %s]",
                len(df),
                pair,
                timeframe,
                df.index[0],
                df.index[-1],
            )

        return df

    def fetch_and_save(
        self,
        pair: str,
        timeframe: str,
        count: int = 5000,
        output_dir: str = "data/historical",
    ) -> Path:
        """Fetch candles and write them to CSV.

        File path: <output_dir>/<pair>_<timeframe>.csv
        Creates output_dir if it does not exist.

        Args:
            pair: OANDA instrument name, e.g. "EUR_USD"
            timeframe: granularity code, e.g. "H1"
            count: candles to request (capped at 5000)
            output_dir: destination directory (relative or absolute)

        Returns:
            Resolved Path to the written CSV file.

        Raises:
            HistoricalFetchError: if no candles are returned.
        """
        df = self.fetch_candles(pair, timeframe, count=count)

        if df.empty:
            raise HistoricalFetchError(
                f"No data returned for {pair} {timeframe} — CSV not written"
            )

        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        filename = out_path / f"{pair}_{timeframe}.csv"
        df.to_csv(filename)
        logger.info("Saved %d rows to %s", len(df), filename)

        return filename.resolve()

    def fetch_all_pairs(
        self,
        pairs: list[str],
        timeframes: list[str],
        count: int = 5000,
        output_dir: str = "data/historical",
        delay: float = 0.5,
    ) -> dict[str, Path | Exception]:
        """Fetch and save candles for every pair × timeframe combination.

        Adds *delay* seconds between requests to respect OANDA rate limits.
        Continues past individual failures so one bad pair does not abort the run.

        Args:
            pairs: list of OANDA instrument names
            timeframes: list of granularity codes
            count: candles per request (capped at 5000)
            output_dir: destination directory
            delay: seconds to sleep between requests

        Returns:
            Dict keyed by "<pair>_<timeframe>" mapping to either the saved
            Path on success or the Exception on failure.
        """
        results: dict[str, Path | Exception] = {}
        total = len(pairs) * len(timeframes)
        current = 0

        for pair in pairs:
            for timeframe in timeframes:
                current += 1
                key = f"{pair}_{timeframe}"
                logger.info("[%d/%d] %s", current, total, key)

                try:
                    path = self.fetch_and_save(
                        pair, timeframe, count=count, output_dir=output_dir
                    )
                    results[key] = path
                except Exception as exc:
                    logger.error("Failed %s: %s", key, exc)
                    results[key] = exc

                if current < total:
                    time.sleep(delay)

        return results
