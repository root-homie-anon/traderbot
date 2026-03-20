# Adaptive Price Action Trading Bot

Automated trading bot using multi-timeframe price action analysis. Backtests on historical data, validates through paper trading (200+ trades), then adapts in real-time based on live performance metrics.

**Goal:** Start with $300, scale to $250+/day through systematic price action trading.

**Status:** Testing — actively paper trading on OANDA practice account. Collecting data to validate strategy before going live.

---

## Quick Start

```bash
# Install dependencies
pip install pandas numpy pytest requests

# Run backtest with sample data
python3 -m src.main --mode backtest

# Run tests (151 passing)
python3 -m pytest tests/ -v

# Paper trade (requires OANDA practice account)
export OANDA_API_KEY="your-api-token"
export OANDA_ACCOUNT_ID="your-account-id"
python3 -m src.main --mode paper --pairs EUR_USD GBP_USD --timeframes H1
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
├── learning/       # Adaptive engine, performance tracking, self-correction, pair selection
├── broker/         # OANDA connector, broker ABC, order management, trade logging
├── utils/          # Helpers, validators, formatters
├── paper_trader.py # Paper trading engine (poll → signal → order → learn loop)
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
| 3. Paper Trading | Testing | OANDA connector, order manager, paper trading engine with adaptive scoring |
| 4. Learning System | Testing | Performance tracking, adaptive score adjustment, self-correction, pair selection |
| 5. Live Trading | TODO | Switch from practice to live OANDA account |

---

## Paper Trading

The paper trading engine connects to OANDA's practice account and runs a continuous loop:

1. **Poll** candles for each pair/timeframe
2. **Detect** signals (reversal, pullback, buildup, BOS)
3. **Score** signals with adaptive quality adjustment based on tracked performance
4. **Place** paper orders with position sizing and risk management
5. **Learn** — self-corrector disables failing setups, pair selector rotates to best performers

```bash
python3 -m src.main --mode paper \
  --pairs EUR_USD GBP_USD USD_JPY \
  --timeframes H1 \
  --poll-interval 120 \
  --max-trades 3
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OANDA_API_KEY` | Yes | OANDA API token (from account settings) |
| `OANDA_ACCOUNT_ID` | Yes | Account ID (e.g. "101-001-12345678-001") |
| `OANDA_ENVIRONMENT` | No | "practice" (default) or "live" |

---

## Signal Types

- **Reversal** — Rejection patterns (pin bar, engulfing, doji) at S/R levels
- **Pullback** — First retracement entry after a strong move (30-70% Fib zone)
- **Buildup** — Breakout from consolidation with narrowing ranges
- **BOS** — Break of structure confirming trend continuation/reversal

## Quality Scoring (6-Factor)

Each signal is scored 0-100 based on:
1. Backtest performance (historical win rate for setup type)
2. Live performance (recent win rate — adaptive)
3. Confluence (multi-timeframe alignment)
4. Trend strength
5. Market regime suitability
6. Risk/reward ratio quality

## Learning System

- **Performance Tracker** — SQLite-backed stats per pair, signal type, timeframe
- **Adaptive Engine** — boosts quality scores for strong setups (>60% WR), penalizes weak (<40%)
- **Self-Corrector** — auto-disables signal types below 30% WR, re-enables on recovery above 50%
- **Pair Selector** — ranks pairs by expectancy, trades top N, drops underperformers

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

## Tests

151 tests across 8 test files:

```
tests/test_price_action.py   — price action analysis
tests/test_signals.py        — signal generation
tests/test_risk.py           — risk management
tests/test_backtest.py       — backtesting engine
tests/test_learning.py       — learning system (30 tests)
tests/test_broker.py         — broker infrastructure (16 tests)
tests/test_paper_trader.py   — paper trading engine (16 tests)
tests/test_utils.py          — utilities (21 tests)
```

```bash
python3 -m pytest tests/ -v
```

---

## Tech Stack

- Python 3.10+, pandas, numpy, requests
- SQLite (performance tracking, trade logging)
- pytest (151 tests passing)
- Brokers: OANDA v20 REST API (forex), Binance (crypto — planned)

---

## TODO

- [x] Set up OANDA practice account and configure API credentials
- [ ] Run 200+ paper trades to validate strategy on live data
- [ ] Compare paper trading metrics against backtest results
- [ ] Implement Binance connector for crypto pairs
- [ ] Build live trading mode (Phase 5) once paper results are validated
- [ ] Add real-time monitoring dashboard / alerts

---

## Disclaimer

This bot trades real money and can lose. Run 200+ paper trades before going live. Start with small capital. Use stop losses. You are responsible for all trading decisions and losses. This is NOT investment advice.

---

**Last Updated:** March 20, 2026
