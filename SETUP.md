# Setup Guide - PA Trading Bot

Complete instructions for setting up the bot on your machine.

---

## Prerequisites

### System Requirements
- **OS:** Linux, macOS, or Windows
- **Python:** 3.10 or higher
- **RAM:** 4GB minimum (8GB recommended)
- **Storage:** 5GB for historical data + database
- **Internet:** Stable connection (for data downloads and live trading)

### Software
- Git (for cloning repo)
- Python 3.10+
- pip (Python package manager)

### Accounts (Free)
- **OANDA:** https://www.oanda.com (demo or live account)
- **Python IDE:** VSCode, PyCharm, or similar (optional)

---

## Step 1: Clone Repository

```bash
git clone https://github.com/yourusername/pa-trading-bot.git
cd pa-trading-bot
```

---

## Step 2: Create Python Virtual Environment

### macOS / Linux
```bash
python3 -m venv venv
source venv/bin/activate
```

### Windows
```bash
python -m venv venv
venv\Scripts\activate
```

Verify activation:
```bash
which python  # macOS/Linux - should show venv path
where python  # Windows - should show venv path
```

---

## Step 3: Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

This installs:
- pandas, numpy (data handling)
- requests (API calls)
- oanda-v20 (OANDA broker)
- python-binance (Binance broker)
- pytest, pytest-cov (testing)
- matplotlib, plotly (visualization)
- And more (see requirements.txt)

Verify installation:
```bash
python -c "import pandas; print(pandas.__version__)"
```

---

## Step 4: Create OANDA Account (Demo or Live)

### Demo Account (Free, Recommended for Learning)
1. Go to https://www.oanda.com
2. Click "Create Account" or "Open Demo Account"
3. Fill out form and verify email
4. Login to your demo account
5. In account settings, generate API token
6. Save credentials (you'll need them next)

### Live Account (Real Money)
1. Follow same steps but choose live account
2. Deposit funds ($300+ recommended for starting)
3. Generate API token
4. **Use demo for 200 paper trades FIRST**

---

## Step 5: Configure Bot

### Create Configuration File

Create `data/config.json`:

```json
{
  "broker": {
    "name": "OANDA",
    "account_id": "YOUR_ACCOUNT_ID",
    "api_token": "YOUR_API_TOKEN",
    "environment": "practice",
    "mode": "paper"
  },
  
  "trading": {
    "risk_per_trade": 0.01,
    "max_daily_loss": 0.10,
    "max_open_positions": null,
    "quality_score_min": 50,
    "trend_strength_min": 40,
    "confluence_min": 1
  },
  
  "pairs": {
    "primary": ["EUR_USD", "GBP_USD", "USD_JPY"],
    "secondary": ["AUD_USD", "NZD_USD"],
    "auto_selection": true,
    "top_pairs_count": 5
  },
  
  "backtesting": {
    "start_date": "2019-01-01",
    "end_date": "2024-12-31",
    "initial_balance": 10000,
    "test_timeframes": [900, 3600, 14400],
    "test_entry_types": ["close", "break"],
    "test_rr_ratios": [1.5, 2.0, 2.5]
  },
  
  "data": {
    "storage": "sqlite",
    "database_path": "data/trades.db",
    "history_months": 60,
    "update_frequency": "daily"
  },
  
  "logging": {
    "level": "INFO",
    "file": "logs/bot.log",
    "console": true
  }
}
```

### Environment Variables (Alternative)

Instead of config.json, use environment variables:

```bash
# macOS/Linux
export OANDA_ACCOUNT_ID="your_account_id"
export OANDA_API_TOKEN="your_api_token"
export BOT_MODE="paper"

# Windows (PowerShell)
$env:OANDA_ACCOUNT_ID="your_account_id"
$env:OANDA_API_TOKEN="your_api_token"
$env:BOT_MODE="paper"
```

Bot will read from env vars if config.json not found.

---

## Step 6: Download Historical Data

```bash
python src/data/data_loader.py --pairs EUR_USD GBP_USD USD_JPY --months 60
```

This downloads 5 years of OHLC data for the specified pairs.

**Options:**
- `--pairs` - Which pairs to download (space-separated)
- `--months` - How many months of history (default 60)
- `--timeframes` - Which timeframes (900s, 3600s, 14400s, etc.)

Verify download:
```bash
python -c "import sqlite3; conn = sqlite3.connect('data/trades.db'); print(conn.execute('SELECT COUNT(*) FROM ohlc_data').fetchone())"
```

---

## Step 7: Run Backtest

```bash
python src/main.py --mode backtest --pairs EUR_USD GBP_USD
```

**Output:**
- Console report (win rate, profit factor, etc.)
- CSV file: `data/backtest_results/report_YYYYMMDD.csv`
- Metrics: `data/backtest_results/metrics_YYYYMMDD.json`

**Options:**
- `--pairs` - Which pairs to test
- `--start-date` - Backtest start date (YYYY-MM-DD)
- `--end-date` - Backtest end date (YYYY-MM-DD)
- `--timeframes` - Which timeframes to test (900, 3600, 14400)
- `--verbose` - Print detailed trade logs

---

## Step 8: Test with Paper Trading

```bash
python src/main.py --mode paper --pairs EUR_USD GBP_USD USD_JPY
```

This:
1. Connects to OANDA demo account (from config)
2. Analyzes live price data
3. Generates trade signals
4. **Places orders on demo account (NO REAL MONEY)**
5. Logs all trades
6. Tracks performance

**Monitor progress:**
```bash
# Watch bot output in real-time
tail -f logs/bot.log

# Or use dashboard (when available)
python notebooks/live_metrics.ipynb
```

---

## Step 9: Run Unit Tests

Before going live, verify everything works:

```bash
# Run all tests
pytest tests/ -v

# Run specific test
pytest tests/test_price_action.py -v

# Run with coverage
pytest tests/ --cov=src --cov-report=html
```

Check coverage: `open htmlcov/index.html` (macOS) or `start htmlcov\index.html` (Windows)

---

## Step 10: Go Live (After 200+ Paper Trades)

Once you've validated the bot with 200+ paper trades:

### Switch to Live Account

Change `config.json`:
```json
{
  "broker": {
    "environment": "live",     // Changed from "practice"
    "mode": "live",             // Changed from "paper"
    "account_id": "LIVE_ACCOUNT_ID",
    "api_token": "LIVE_API_TOKEN"
  }
}
```

### Start Live Bot

```bash
python src/main.py --mode live --pairs EUR_USD GBP_USD --risk 0.01
```

**Safety Features:**
- 10% daily loss limit (auto-stops)
- 1% risk per trade (limit losses)
- Position size capped
- All trades logged
- Email alerts (coming soon)

---

## Troubleshooting

### Issue: "ModuleNotFoundError: No module named 'oanda'"
**Solution:**
```bash
pip install oanda-v20
```

### Issue: "API request failed: Authentication failed"
**Solution:**
- Check `OANDA_API_TOKEN` is correct
- Verify account ID in config
- Ensure account is active (check OANDA website)

### Issue: "No historical data found"
**Solution:**
```bash
python src/data/data_loader.py --pairs EUR_USD --months 60 --force
```

### Issue: "Bot won't start / Connection timeout"
**Solution:**
- Check internet connection
- Verify OANDA API is up (https://www.oanda.com/status)
- Check logs: `tail -f logs/bot.log`
- Try again in 30 seconds

### Issue: "Position size calculation error"
**Solution:**
- Verify account balance > $0
- Check stop loss distance is valid (>5 pips)
- Ensure risk per trade is 0.01-0.05 (1-5%)

---

## Project Structure

After setup, you'll have:

```
pa-trading-bot/
├── src/
│   ├── config.py              # Load configuration
│   ├── logger.py              # Logging setup
│   ├── main.py                # Bot entry point
│   ├── data/                  # Data handling
│   │   ├── data_loader.py     # Download OHLC
│   │   └── database.py        # SQLite interface
│   ├── analysis/              # PA detection
│   ├── signals/               # Signal generation
│   ├── backtest/              # Backtesting
│   ├── learning/              # Learning system
│   ├── risk/                  # Risk management
│   └── broker/                # Broker APIs
│
├── data/
│   ├── config.json            # Your configuration
│   ├── trades.db              # SQLite database
│   ├── historical/            # Downloaded OHLC data
│   └── backtest_results/      # Backtest reports
│
├── logs/
│   └── bot.log                # Bot activity log
│
├── tests/                     # Unit tests
├── notebooks/                 # Analysis notebooks
│
└── requirements.txt           # Python dependencies
```

---

## Usage Commands

### Common Commands

```bash
# Backtest a strategy
python src/main.py --mode backtest --pairs EUR_USD GBP_USD

# Paper trade (demo account)
python src/main.py --mode paper --pairs EUR_USD GBP_USD USD_JPY

# Live trade (REAL MONEY - after 200+ paper trades)
python src/main.py --mode live --pairs EUR_USD GBP_USD

# Run tests
pytest tests/ -v

# Generate report
python src/backtest/reporter.py --start 2024-01-01 --end 2024-12-31

# Check logs
tail -f logs/bot.log

# Monitor live performance (coming soon)
python notebooks/live_metrics.ipynb
```

---

## Configuration Reference

### broker
- `name` - "OANDA" or "BINANCE"
- `account_id` - Your broker account ID
- `api_token` - Your API token (keep secret!)
- `environment` - "practice" (demo) or "live"
- `mode` - "paper" (simulated) or "live" (real money)

### trading
- `risk_per_trade` - 0.01 (1%), adjustable 0.005-0.05
- `max_daily_loss` - 0.10 (10%), adjustable
- `max_open_positions` - null (unlimited), or set to number
- `quality_score_min` - 50 (0-100 scale, higher = stricter)
- `trend_strength_min` - 40 (0-100 scale)
- `confluence_min` - 1 (1x, 2x, or 3x stacked levels required)

### pairs
- `primary` - Always trade these pairs
- `secondary` - Trade if primary unavailable
- `auto_selection` - Let bot pick best pairs dynamically
- `top_pairs_count` - Max pairs to trade simultaneously

### backtesting
- `start_date` - Backtest from this date
- `end_date` - Backtest to this date
- `initial_balance` - Starting capital for simulation
- `test_timeframes` - 900 (15min), 3600 (1H), 14400 (4H), 86400 (daily)
- `test_entry_types` - "close" (end of candle) or "break" (immediately)
- `test_rr_ratios` - 1.5 (1:1.5), 2.0 (1:2), 2.5 (1:2.5)

### data
- `storage` - "sqlite" (recommended)
- `database_path` - Where to store database
- `history_months` - How many months of data to keep
- `update_frequency` - "daily" or "hourly"

### logging
- `level` - "DEBUG", "INFO", "WARNING", "ERROR"
- `file` - Where to write logs
- `console` - true/false (print to console too)

---

## Next Steps

### After Setup Complete:

1. **Verify Installation**
   ```bash
   pytest tests/ -v
   ```

2. **Run First Backtest**
   ```bash
   python src/main.py --mode backtest --pairs EUR_USD --verbose
   ```

3. **Review Results**
   ```bash
   cat data/backtest_results/report_*.csv
   ```

4. **Start Paper Trading**
   ```bash
   python src/main.py --mode paper --pairs EUR_USD GBP_USD USD_JPY
   ```

5. **Monitor Performance**
   - Check logs: `tail -f logs/bot.log`
   - Wait for 200+ trades
   - Verify live performance ±10% of backtest

6. **Go Live** (When ready)
   - Update config with live account
   - Start bot: `python src/main.py --mode live --pairs EUR_USD`
   - Monitor daily

---

## Getting Help

### Documentation
- `docs/PROJECT_OVERVIEW.md` - Architecture
- `docs/PAIR_SELECTION.md` - Pair framework
- `docs/BROKER_ANALYSIS.md` - Broker setup

### Debugging
- Check `logs/bot.log` for errors
- Run tests: `pytest tests/ -v`
- Enable verbose logging: `--verbose` flag

### Support
- GitHub Issues (coming)
- GitHub Discussions (coming)

---

## Security Notes

⚠️ **IMPORTANT:**

1. **API Token** - Never commit to GitHub!
   ```bash
   # Add to .gitignore
   echo "data/config.json" >> .gitignore
   echo ".env" >> .gitignore
   ```

2. **Environment Variables** - Use for sensitive data
   ```bash
   export OANDA_API_TOKEN="your_token_here"
   # Bot will read from env var
   ```

3. **Permissions** - Restrict file access
   ```bash
   chmod 600 data/config.json  # Only you can read
   ```

4. **Backups** - Keep your settings safe
   ```bash
   cp data/config.json data/config.json.backup
   ```

---

## Updating the Bot

When new versions are released:

```bash
git pull origin main
pip install -r requirements.txt --upgrade
pytest tests/ -v  # Verify nothing broke
```

---

**You're all set!** Ready to build the trading bot. 🚀

For questions, check the docs or open a GitHub issue.
