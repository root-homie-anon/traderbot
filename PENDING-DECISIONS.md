# Pending Decisions

## 1. Paper bot auto-restart (open)
`com.traderbot.paper` is still registered and **will start again Sunday 17:00**.
It runs a configuration measured as negative-expectancy (5,594-trade backtest:
-0.115R/trade; `reversal` worst at -0.165R over 3,167 trades).

- To stop permanently: `launchctl bootout gui/$(id -u)/com.traderbot.paper`
- To leave it collecting paper data: do nothing.

## 2. Strategy direction (open)
Four strategy families tested and rejected on evidence — see research summary.
Trend-as-a-sleeve is the only survivor, and the finding is that it should be
*bought* (DBMF/KMLM), not built.

Open question: keep this repo as a research platform, or archive it.

## 3. Dead code removal (not started)
~2,000 lines measured as adding nothing: `src/learning/` (adaptive engine,
self-corrector, pair selector), `src/signals/quality_scorer.py`, and most of
`src/analysis/` (confluence, regime, MTF, order book, COT).

## 4. Research dependency
`yfinance` was added to `.venv` for multi-asset data. Not in requirements.txt.
