# Adaptive Price Action Trading Bot

An autonomous, self-learning forex/crypto trading bot using multi-timeframe price action analysis. Backtests on historical data, validates through paper trading (200+ trades), then adapts in real-time based on live performance metrics.

**Goal:** Start with $300 → Scale to $250+/day profitability through intelligent, data-driven price action trading.

**Status:** Pre-development (planning complete, ready to code Phase 1)

---

## Quick Start

### Prerequisites
- Python 3.10+
- OANDA demo/live account (free)
- 2-5 years of historical OHLC data (will be downloaded automatically)

### Setup (Coming in Phase 1)
```bash
git clone https://github.com/yourusername/pa-trading-bot.git
cd pa-trading-bot
pip install -r requirements.txt
python src/main.py --mode backtest
```

---

## Core Features

### ✅ Strategy Foundation
- **Multi-timeframe price action** (4-6x factor alignment)
- **Market structure classification** (Accumulation/Advancing/Distribution/Declining)
- **Support/resistance detection** (3+ touch method)
- **Trend strength validation** (candle size analysis)
- **Break of structure detection** (higher highs/lows vs lower highs/lows)
- **Entry confirmation** (power moves, build-ups, first pullbacks)

### ✅ Backtesting Engine
- Test 2-5 years of historical data per pair
- Optimize: timeframe, entry type, R:R ratio
- Generate: win rate, profit factor, Sharpe ratio, max drawdown

### ✅ Paper Trading Phase
- 200+ risk-free trades on real market data
- Validate backtest assumptions
- Identify best-performing setups

### ✅ Adaptive Learning System
- **6-factor quality scoring** (backtest performance, live performance, confluence, trend strength, regime, R:R)
- **Per-pair performance tracking** (win rate, profit factor by pair/timeframe/setup type)
- **Self-correction** (15% performance drop triggers adjustment)
- **Dynamic pair selection** (best pairs only)
- **Market regime detection** (trending vs ranging)

### ✅ Risk Management
- 1% risk per trade (adjustable)
- Position sizing based on stop loss distance
- 10% daily loss limit (adjustable)
- Drawdown management (reduce size on large losses)
- Multi-level stop loss validation

### ✅ Broker Integration
- **OANDA** (forex/CFDs) - primary
- **Binance** (crypto) - secondary (optional)
- Paper → Live seamless transition
- Real-time data streaming
- Order management

---

## Architecture

### System Components

```
┌─────────────────────────────────────────────────────────────┐
│                    PRICE ACTION BOT                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ DATA LAYER   │  │ ANALYSIS     │  │ SIGNALS      │      │
│  ├──────────────┤  │ ENGINE       │  ├──────────────┤      │
│  │• Download    │  ├──────────────┤  │• Reversal    │      │
│  │  OHLC data   │  │• S/R detect  │  │• Build-up    │      │
│  │• Clean data  │  │• Structure   │  │• 1st pullback│      │
│  │• SQLite DB   │  │• Confluence  │  │• BOS         │      │
│  │• Validation  │  │• Trend       │  │• Quality     │      │
│  └──────────────┘  │  strength    │  │  scoring     │      │
│                    └──────────────┘  └──────────────┘      │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ BACKTEST     │  │ LEARNING     │  │ RISK MGMT    │      │
│  │ ENGINE       │  │ ENGINE       │  ├──────────────┤      │
│  ├──────────────┤  ├──────────────┤  │• Position    │      │
│  │• Simulate    │  │• Track perf  │  │  sizing      │      │
│  │  trades      │  │• Per-pair    │  │• Stop loss   │      │
│  │• Metrics     │  │  metrics     │  │• Daily limit │      │
│  │• Optimize    │  │• Self-correct│  │• Drawdown    │      │
│  │  configs     │  │• Pair select │  │  mgmt        │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐                         │
│  │ BROKER       │  │ MAIN BOT     │                         │
│  │ CONNECTOR    │  │ LOOP         │                         │
│  ├──────────────┤  ├──────────────┤                         │
│  │• OANDA API   │  │• Monitor     │                         │
│  │• Order mgmt  │  │  prices      │                         │
│  │• Trade log   │  │• Gen signals │                         │
│  │• Real-time   │  │• Manage pos  │                         │
│  │  data        │  │• Log trades  │                         │
│  └──────────────┘  └──────────────┘                         │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### File Structure
```
pa-trading-bot/
├── docs/
│   ├── PROJECT_OVERVIEW.md          # Full architecture
│   ├── BROKER_ANALYSIS.md           # Broker comparison
│   ├── PAIR_SELECTION.md            # Pair framework
│   └── DEVELOPMENT_LOG.md           # Phase progress
│
├── src/
│   ├── config.py                    # Configuration
│   ├── logger.py                    # Logging
│   ├── data/                        # Data handling
│   ├── analysis/                    # PA detection
│   ├── signals/                     # Signal generation
│   ├── backtest/                    # Backtesting
│   ├── learning/                    # Adaptive learning
│   ├── risk/                        # Risk management
│   ├── broker/                      # Broker APIs
│   └── main.py                      # Bot entry point
│
├── tests/                           # Unit tests
├── notebooks/                       # Analysis notebooks
├── data/                            # Data storage
├── requirements.txt                 # Dependencies
├── setup.py                         # Install script
├── SETUP.md                         # Setup guide
└── LICENSE                          # MIT License
```

---

## Development Phases

| Phase | Duration | Goal | Status |
|-------|----------|------|--------|
| **1: Strategy Engine** | 2 weeks | Core PA detection | 🎯 Ready to start |
| **2: Backtesting** | 2 weeks | Historical validation | Blocked by Phase 1 |
| **3: Paper Trading** | 2-4 weeks | 200+ trades, live validation | Blocked by Phase 2 |
| **4: Learning System** | 1-2 weeks | Adaptive engine active | Blocked by Phase 3 |
| **5: Broker Integration** | 1-2 weeks | Live trading ready | Blocked by Phase 4 |

**Total:** 8-12 weeks to live trading

---

## Configuration

### Default Parameters
```python
# Risk Management
RISK_PER_TRADE = 0.01  # 1% of account
MAX_DAILY_LOSS = 0.10  # 10% of account
MAX_POSITIONS = None   # Unlimited within risk

# Entry Rules
CONFLUENCE_MIN = 1     # Min confluence level (1x, 2x, 3x)
TREND_STRENGTH_MIN = 40  # Minimum trend strength (0-100)
QUALITY_SCORE_MIN = 50   # Minimum quality score (0-100)

# Pair Selection
TOP_PAIRS = 5          # Trade top 5 pairs
AUTO_PAIR_SELECTION = True  # Dynamic pair selection

# Broker
BROKER = "OANDA"       # OANDA (forex) or BINANCE (crypto)
TRADING_MODE = "paper" # "paper" or "live"
```

All parameters adjustable via `src/config.py`

---

## Trading Rules (From Price Action Foundation)

### Market Structure
- **Accumulation:** Range after downtrend → prepare for uptrend breakout
- **Advancing:** Uptrend (higher highs/lows) → only buy at pullbacks
- **Distribution:** Range after uptrend → prepare for downtrend breakdown
- **Declining:** Downtrend (lower highs/lows) → only sell at rallies

### Entry Confirmation
- **Reversal:** Power move into support/resistance + rejection candle
- **Build-up:** Tight consolidation + breakout above/below
- **First Pullback:** Breakout + first retracement (high probability)
- **Break of Structure:** New higher high/low in trend direction

### Risk Management
- **Stop Loss:** Distance away from market structure (not right at level)
- **Profit Target:** Next major swing level or 2:1+ R:R
- **Position Size:** Account × Risk % ÷ Stop distance (in pips)

### Quality Filtering
- **Confluence:** Multi-timeframe alignment (4-6x factor)
- **Trend Strength:** Large candles in trend, small candles in retracement
- **Area of Value:** Trade near support/resistance/MA, not away from it
- **No Chase:** Avoid large directional candles (energy released)

---

## Backtesting Results (Coming Soon)

Once Phase 2 complete, you'll see:

```
Pair: EUR/USD
Timeframe: 1H
Entry Type: Close of candle
R:R Ratio: 1:2

Results:
- Win Rate: 56%
- Profit Factor: 1.87
- Sharpe Ratio: 1.42
- Max Drawdown: 12%
- Total Return: 234%
- Sample Size: 487 trades
```

---

## Paper Trading Log (Coming Soon)

Once Phase 3 active:

```
Trade #47
Pair: GBP/USD
Entry: 1.2750 (BUY)
Stop: 1.2735
Target: 1.2785
Confidence: 68/100
Reason: 2x confluence (1H support + 4H resistance now support)
         Trend strength 72/100
         Reversal setup with engulfing candle
Result: HIT TARGET (+35 pips)
```

---

## Live Trading Dashboard (Coming Soon)

Real-time metrics:
- Current account balance
- Win rate (live vs backtest)
- Profit factor
- Open positions
- Daily P&L
- Pair performance
- Adaptive thresholds (current settings)

---

## Dependencies

Core Libraries:
- `pandas` - Data handling
- `numpy` - Numerical analysis
- `requests` - API calls
- `sqlite3` - Database
- `matplotlib` / `plotly` - Visualization

Broker APIs:
- `oanda-v20` - OANDA API
- `python-binance` - Binance API

Testing:
- `pytest` - Unit tests
- `pytest-cov` - Coverage

See `requirements.txt` for full list.

---

## Getting Help

### Documentation
- **PROJECT_OVERVIEW.md** - Complete architecture
- **BROKER_ANALYSIS.md** - Broker setup guide
- **PAIR_SELECTION.md** - How pair selection works
- **SETUP.md** - Installation & configuration

### Issues
- Check `docs/DEVELOPMENT_LOG.md` for known issues
- Open GitHub issue with details

### Community
- Trading strategy discussions: (to be added)
- Bot improvements: Pull requests welcome

---

## Legal & Risk Disclaimer

⚠️ **IMPORTANT:** This bot trades real money and can lose. 

**Before using on live trading:**
1. ✅ Run 200+ paper trades first (validate strategy)
2. ✅ Start with small capital ($300 is fine)
3. ✅ Monitor bot daily (don't set and forget)
4. ✅ Use stop losses religiously
5. ✅ Understand price action trading
6. ✅ Accept that losses will happen

**You are responsible for:**
- All trading decisions
- All financial losses
- Tax reporting
- Regulatory compliance in your jurisdiction

**This is NOT investment advice.** Use at your own risk.

---

## License

MIT License - See LICENSE file

---

## Contributing

Contributions welcome! Please:
1. Fork the repo
2. Create feature branch (`git checkout -b feature/amazing-improvement`)
3. Commit changes (`git commit -m 'Add amazing improvement'`)
4. Push to branch (`git push origin feature/amazing-improvement`)
5. Open Pull Request

---

## Roadmap

### Q1 2025
- ✅ Phase 1: Strategy engine
- ✅ Phase 2: Backtesting
- ✅ Phase 3: Paper trading (200 trades)

### Q2 2025
- ✅ Phase 4: Learning system
- ✅ Phase 5: Broker integration
- 🎯 Live trading on OANDA

### Q3 2025+
- Binance crypto integration
- Advanced machine learning
- Multi-strategy framework
- Cloud deployment

---

## Authors

- **You** - Strategy, pair selection, decisions
- **Claude** - Code, architecture, development

---

## Version History

- **v0.1.0** (Pre-development) - Planning complete, ready for Phase 1
- v0.2.0 (Phase 1) - Strategy engine (estimated 2 weeks)
- v0.3.0 (Phase 2) - Backtesting (estimated 2 weeks)
- v1.0.0 (Phase 5) - Live trading ready (estimated 8-12 weeks)

---

## Contact

For questions about this project:
- Open GitHub discussion
- Open GitHub issue
- (Contact method to be added)

---

**Last Updated:** March 10, 2025
**Next Update:** After Phase 1 complete

---

🚀 **Ready to build the best trading bot?** Let's go!
