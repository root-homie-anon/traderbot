"""Validate and clean OHLC data."""

import pandas as pd
import numpy as np


def validate_ohlc(df: pd.DataFrame) -> list[str]:
    """Check OHLC data for common issues. Returns list of warnings."""
    warnings = []

    if df.empty:
        warnings.append("DataFrame is empty")
        return warnings

    # Check required columns
    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        warnings.append(f"Missing columns: {missing}")
        return warnings

    # High should be >= open, close, low
    bad_high = (df["high"] < df["open"]) | (df["high"] < df["close"])
    if bad_high.any():
        warnings.append(f"{bad_high.sum()} rows where high < open or close")

    # Low should be <= open, close, high
    bad_low = (df["low"] > df["open"]) | (df["low"] > df["close"])
    if bad_low.any():
        warnings.append(f"{bad_low.sum()} rows where low > open or close")

    # Check for NaN values
    nan_counts = df[list(required)].isna().sum()
    if nan_counts.any():
        warnings.append(f"NaN values found: {nan_counts.to_dict()}")

    # Check for zero or negative prices
    if (df[list(required)] <= 0).any().any():
        warnings.append("Zero or negative prices found")

    # Check for duplicate indices
    if df.index.duplicated().any():
        warnings.append(f"{df.index.duplicated().sum()} duplicate timestamps")

    # Check monotonic index
    if not df.index.is_monotonic_increasing:
        warnings.append("Index is not sorted chronologically")

    return warnings


def clean_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    """Clean OHLC data by fixing common issues."""
    df = df.copy()

    # Drop rows with NaN in OHLC columns
    ohlc_cols = ["open", "high", "low", "close"]
    df.dropna(subset=ohlc_cols, inplace=True)

    # Remove duplicate timestamps, keep last
    df = df[~df.index.duplicated(keep="last")]

    # Sort by index
    df.sort_index(inplace=True)

    # Fix OHLC consistency
    df["high"] = df[["open", "high", "low", "close"]].max(axis=1)
    df["low"] = df[["open", "high", "low", "close"]].min(axis=1)

    # Remove zero/negative prices
    mask = (df[ohlc_cols] > 0).all(axis=1)
    df = df[mask]

    # Fill missing volume with 0
    if "volume" in df.columns:
        df["volume"] = df["volume"].fillna(0).astype(int)

    return df


def detect_gaps(df: pd.DataFrame, max_gap_multiple: float = 3.0) -> pd.DataFrame:
    """Detect unusual gaps in the data timeline.

    Returns DataFrame of gap locations with expected vs actual intervals.
    """
    if len(df) < 2:
        return pd.DataFrame()

    diffs = df.index.to_series().diff()
    median_diff = diffs.median()
    threshold = median_diff * max_gap_multiple

    gaps = diffs[diffs > threshold]
    if gaps.empty:
        return pd.DataFrame()

    return pd.DataFrame({
        "gap_start": gaps.index - gaps.values,
        "gap_end": gaps.index,
        "gap_duration": gaps.values,
        "expected": median_diff,
    })
