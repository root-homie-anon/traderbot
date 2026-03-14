# Adaptive Price Action Trading Bot

Automated trading bot using multi-timeframe price action analysis. Backtests on historical data, validates through paper trading (200+ trades), then adapts in real-time based on live performance metrics.

**Goal:** Start with $300, scale to $250+/day through systematic price action trading.

**Status:** Phase 2 (Backtesting) complete. Ready for Phase 3 (Paper Trading).

---

## Quick Start

```bash
# Install dependencies
pip install pandas numpy pytest

# Run backtest with sample data
python3 -m src.main --mode backtest

# Run tests (69 passing)
python3 -m pytest tests/ -v
```

---

## Architecture

```
src/
├── data/           # OHLC data loading, cleaning, SQLite storage
├── analysis/       # Price action, S/R, market structure, trend, BOS, confluence
├── signals/        # Signal generation: reversal, pullback, buildup, BOS + quality scoring
├── backtest/       # Walk-forward backtester, metrics, optimizer, reporter
├── risk/           # Position sizing, stop validation, daily limits, drawdown scaling
├── learning/       # (Phase 4) Adaptive engine, performance tracking, self-correction
├── broker/         # (Phase 5) OANDA/Binance connectors, order management
├── config.py       # Configuration and defaults
├── logger.py       # Logging setup
└── main.py         # Entry point (--mode backtest|paper|live)
```

---

## Development Phases

| Phase | Status | Description |
|-------|--------|-------------|
| 1. Strategy Engine | Done | Price action detection, S/R, market structure, signal generation, quality scoring |
| 2. Backtesting | Done | Walk-forward simulation, metrics (Sharpe/PF/DD), parameter optimizer, risk management |
| 3. Paper Trading | Next | 200+ simulated trades on live data to validate strategy |
| 4. Learning System | Planned | Adaptive parameters, self-correction, dynamic pair selection |
| 5. Broker Integration | Planned | OANDA + Binance live execution |

---

## Signal Types

- **Reversal** - Rejection patterns (pin bar, engulfing, doji) at S/R levels
- **Pullback** - First retracement entry after a strong move (30-70% Fib zone)
- **Buildup** - Breakout from consolidation with narrowing ranges
- **BOS** - Break of structure confirming trend continuation/reversal

## Quality Scoring (6-Factor)

Each signal is scored 0-100 based on:
1. Backtest performance (historical win rate for setup type)
2. Live performance (recent win rate)
3. Confluence (multi-timeframe alignment)
4. Trend strength
5. Market regime suitability
6. Risk/reward ratio quality

## Risk Management

- 1% risk per trade (configurable)
- Position sizing based on stop distance
- 10% daily loss limit with automatic lockout
- Drawdown scaling: position size reduced to 0.25x at 20%+ drawdown or 4+ consecutive losses
- Stop validation: direction check, ATR-based bounds, min/max pip limits

## Backtesting Engine

- Walk-forward bar-by-bar simulation (no look-ahead bias)
- Spread simulation
- Integrated risk management (daily limits, drawdown scaling)
- Metrics: win rate, Sharpe ratio, profit factor, max drawdown, expectancy, avg R:R
- Parameter optimizer with grid search
- Walk-forward optimization with in-sample/out-of-sample validation

---

## Configuration

```python
RISK_PER_TRADE = 0.01       # 1% of account
MAX_DAILY_LOSS = 0.10       # 10% of account
CONFLUENCE_MIN = 1          # Min confluence level
TREND_STRENGTH_MIN = 40     # Minimum trend strength (0-100)
QUALITY_SCORE_MIN = 50      # Minimum quality score (0-100)
BROKER = "OANDA"            # OANDA or BINANCE
TRADING_MODE = "paper"      # "paper" or "live"
TIMEFRAMES = ["M15", "H1", "H4", "D"]
```

---

## Tech Stack

- Python 3.10+, pandas, numpy
- SQLite (trade database)
- pytest (69 tests passing)
- Brokers: OANDA (forex), Binance (crypto)

---

## Disclaimer

This bot trades real money and can lose. Run 200+ paper trades before going live. Start with small capital. Use stop losses. You are responsible for all trading decisions and losses. This is NOT investment advice.

---

**Last Updated:** March 14, 2026
