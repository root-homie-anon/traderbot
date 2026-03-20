# Changelog

All notable changes to this project will be documented in this file.

---

## [0.5.0] - 2026-03-20

### Paper Trading Live Testing

#### Fixed
- JPY pair price precision — orders were rejected because OANDA requires 3 decimal places for JPY pairs, not 5
- Duplicate trade protection — only one open trade per pair allowed (was stacking identical positions)
- Learning system not recording — `_check_closed_trades()` was a stub; now fully wired to performance DB

#### Added
- Early take-profit at 50% of target — closes trades when price reaches halfway to TP
- Broker trade backfill on startup — picks up existing open trades so early TP and learning work across restarts
- Signal metadata tracking — stores signal type, timeframe, quality score with each order for learning
- Deferred pair selection — uses all configured pairs until enough performance data is collected

#### Changed
- Pair selector no longer overrides configured pairs when it has no data
- Price formatting is now instrument-aware (`_fmt_price` / `_price_precision`)

---

## [0.4.0] - 2026-03-15

### Phase 3: Paper Trading + Phase 4: Learning System

#### Added — Paper Trading Engine
- `src/paper_trader.py` — Complete paper trading loop: poll candles, generate signals, adaptive scoring, place orders, track performance, self-correct
- `src/broker/oanda_connector.py` — Full OANDA v20 REST API connector (candles, market orders, trade management, spread, account info)
- `src/broker/broker_base.py` — Abstract base class defining the broker contract
- `src/broker/order_manager.py` — Signal-to-order lifecycle with position sizing, drawdown scaling, daily limits, conflict detection
- `src/broker/trade_logger.py` — SQLite append-only trade log for auditing and replay
- CLI support: `--mode paper`, `--pairs`, `--timeframes`, `--poll-interval`, `--max-cycles`, `--max-trades`

#### Added — Learning System
- `src/learning/performance_tracker.py` — SQLite-backed per-pair/signal-type/timeframe performance stats (win rate, expectancy, profit factor, pair rankings)
- `src/learning/adaptive_engine.py` — Quality score multipliers from tracked performance with specificity fallback and confidence blending
- `src/learning/self_corrector.py` — Auto-disable signal types below 30% win rate, warn at 40%, remove pairs below 25%, re-enable on recovery above 50%
- `src/learning/pair_selector.py` — Rank pairs by expectancy, select top N, min win rate filter, fallback to defaults

#### Added — Utilities
- `src/utils/helpers.py` — Pip/price conversions, timeframe mapping, OHLC resampling
- `src/utils/validators.py` — OHLC data validation, signal consistency checks, pair format validation
- `src/utils/formatters.py` — PnL, percentage, stats table, and trade summary formatting

#### Tests
- 82 new tests across 4 new test files (test_learning, test_broker, test_paper_trader, test_utils)
- **Total: 151 tests, all passing**

---

## [0.2.0] - 2026-03-14

### Phase 1: Strategy Engine + Phase 2: Backtesting

#### Added — Strategy Engine
- `src/analysis/` — Price action detection, support/resistance, market structure, trend strength, break of structure, confluence
- `src/signals/` — 4 signal types (reversal, pullback, buildup, BOS) with 6-factor quality scoring
- `src/data/` — OHLC data loading, cleaning, SQLite storage

#### Added — Backtesting
- `src/backtest/backtester.py` — Walk-forward bar-by-bar simulation with spread simulation
- `src/backtest/metrics.py` — Win rate, Sharpe ratio, profit factor, max drawdown, expectancy
- `src/backtest/optimizer.py` — Parameter grid search + walk-forward optimization
- `src/backtest/reporter.py` — Text report generation with grading

#### Added — Risk Management
- `src/risk/position_sizer.py` — Position sizing based on account balance, risk %, stop distance
- `src/risk/stop_validator.py` — Stop loss validation (direction, min/max pips, ATR-based)
- `src/risk/daily_limits.py` — Daily loss limit tracking and enforcement
- `src/risk/drawdown_manager.py` — Drawdown-based and consecutive-loss position scaling

#### Tests
- 69 tests, all passing

---

## [0.1.0] - 2025-03-10

### Planning Release

#### Added
- Project overview documentation
- Broker selection analysis (OANDA recommended)
- Pair selection framework (10-factor scoring)
- Repository structure and development roadmap
- Setup guide and contributing guidelines

---

## TODO

- [x] OANDA practice account setup — actively paper trading
- [ ] Collect 200+ paper trades to validate strategy
- [ ] Binance connector for crypto pairs
- [ ] Phase 5: Live trading mode
- [ ] Monitoring dashboard / alerts

---

**Last Updated:** March 20, 2026
