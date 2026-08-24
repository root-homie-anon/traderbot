# Adaptive Price Action Trading Bot — Post-Mortem

**Status: discontinued, 2026-08-23.** This repository is archived. The strategy
was tested to destruction and does not work. This README documents what was
built, what was measured, and why the project was stopped, so the conclusions
outlive the code.

---

## The original goal

> Start with $300, scale to $250+/day through systematic price action trading.

Worth stating plainly at the top, because it framed everything that followed:
that target implies roughly 80% per day. Nothing in public markets does that.
A realistic ceiling for a well-executed retail systematic strategy is a Sharpe
ratio around 0.5 — meaning single-digit annual percentage returns with 20-30%
drawdowns. The gap between the goal and the achievable was roughly four orders
of magnitude, and it drove a lot of complexity that could never have paid off.

## What was built

A complete automated trading system against the OANDA v20 API:

- Four price-action signal generators (reversal, pullback, buildup, break-of-structure)
- A six-factor quality scorer, confluence analysis, regime detection,
  multi-timeframe confirmation, order-book sentiment, COT positioning,
  economic-calendar blackouts
- An adaptive learning layer: performance tracker, adaptive engine, self-corrector,
  pair selector, re-entry cooldowns
- Risk management: fractional sizing, drawdown scaling, daily loss limits
- An event-driven backtester with no look-ahead, filling on next-bar open
- Paper-trading engine with authoritative trade reconciliation against OANDA
- launchd-based weekly scheduling (start Sunday 17:00, stop Friday 17:00)
- 226 passing tests

The infrastructure worked. The strategy did not.

## What went wrong

### 1. Live results

34 paper trades over four months on an OANDA practice account:

| metric | value |
|---|---|
| Win rate | 23.5% (8/34) |
| Avg win / avg loss | +1.18R / -0.86R |
| Total | **-12.8R, -$14,584, -17% of account** |

Break-even at that win/loss ratio required a 42% win rate.

### 2. Ten weeks of silent inactivity

From June to August 2026 the bot ran ~1,000 hours and placed **zero orders**.

Cause: the self-corrector disabled a signal type after 5 consecutive losses, but
re-enabling required 50 trades. A disabled signal stops trading, so its trade
count froze below the threshold and the re-enable branch became unreachable.
Three of four signal types were permanently disabled; the survivor (`reversal`)
never produced a signal that cleared the quality gate.

A one-way ratchet that could only ever remove capability, and eventually removed
all of it. Fixed in `9d62a9d` (probation-based expiry), but the subsystem should
never have existed — see below.

### 3. The strategy has no edge

The decisive test. The backtester had never been run: `performance.db` contained
zero rows with `source='backtest'`. Running it across 4 pairs x 10 months of H1
data produced **5,594 out-of-sample trades** — 165x the live sample.

| signal | n | win% | expectancy | zero-cost expectancy |
|---|---|---|---|---|
| reversal | 3,167 | 22.4% | -0.165R | -0.084R |
| pullback | 202 | 31.2% | -0.012R | +0.050R |
| buildup | 672 | 33.6% | -0.032R | -0.001R |
| bos | 1,553 | 33.2% | -0.061R | -0.006R |
| **all** | **5,594** | **27.0%** | **-0.115R** | **-0.048R** |

"Zero-cost" removes all transaction costs. **The strategy loses even with no
spread at all.** `buildup` and `bos` are coin flips to three decimal places.
This is not a tuning problem; there is no edge to tune.

### 4. The filtering stack contributed nothing

The six-factor quality scorer lifted win rate from 24.8% to 31.0% across score
bands — but average win shrank from 2.67R to 2.17R in near-exact compensation.
No threshold was profitable at any level. The production gate of 55 sat at
-0.100R expectancy.

Roughly 2,000 lines of scoring, confluence, regime, MTF, order-book, COT and
adaptive-learning code were, in aggregate, filtering coin flips.

## Bugs found and fixed along the way

| commit | issue |
|---|---|
| `f5857d0` | A hyphenated key synced into `.env` broke `source .env` under `set -e`, killing the Sunday auto-start with exit 127 |
| `9d62a9d` | Self-corrector ratchet (above); also a frozen pair streak re-emitted the same warning every cycle — 2,226 identical lines per 3,000 |
| `7caab8a` | `risk_amount` was never persisted to `signal_meta`, so any trade held across a restart had its dollar risk re-derived from the *current* setting. One trade recorded -4.54R that was actually a normal 1R stop-out. Corrupted every R-multiple for weekend-held trades — and the bot restarts weekly by design |
| `5c26724` | Self-corrector disabled by default; positions now flattened before the Friday close, since a resting stop does not bound a weekend gap (one EUR_USD trade realised 2.46R on a 1R stop at a Sunday reopen) |

## Alternatives tested before stopping

Each was tested with textbook parameters — not searched until something paid.

**FX currency momentum** (68 pairs, 18 years daily). Cross-sectional 12-1
momentum: Sharpe 0.68 headline — but attribution showed **TRY was 102% of all
P&L**, i.e. "short Turkish lira for eight years." Spot-only backtests cannot
price the 8-50% financing cost of that short. Excluding EM, G10 momentum was
**Sharpe 0.00** across every lookback and portfolio width. Time-series momentum
on G10: Sharpe 0.10.

**Crypto trend following** (34 coins, 2019-2026). Full sample Sharpe 0.93,
beating buy-and-hold BTC. Split by regime:

| period | BTC hold | TSMOM 100d |
|---|---|---|
| 2019-09 to 2021-12 | 1.26 | **3.20** |
| 2022-01 to 2026-08 | 0.15 | **-0.23** |

All of it was the 2020-21 bull run. In the 4.5 years since, trend following lost
money and underperformed simply holding BTC. The best in-sample parameter (100d)
became the worst out-of-sample — the signature of fitting noise. Results are also
survivorship-biased: the universe was selected on present-day volume.

**Multi-asset futures trend following** (35 markets, 7 sectors, 26 years). The
one configuration where the diversification math should work.

## The root cause of every failure: breadth

Holding the strategy fixed and varying only the number of sectors in the book:

| sectors | independent bets | Sharpe |
|---|---|---|
| 1 | 2.5 | -0.07 |
| 3 | 5.7 | 0.03 |
| 5 | 8.6 | 0.11 |
| 7 | **11.7** | **0.19** |

Sharpe scales with the square root of independent bets. Measured breadth:

- FX (10 G10 currencies): **2.6** independent bets — USD factor is 59% of variance
- Crypto (30 coins): **3.7** — BTC factor is 51%, mean correlation to BTC 0.54
- Multi-asset futures (35 markets): **11.7** — mean pairwise correlation 0.14

68 currency pairs is not 68 bets; it is the USD trade with noise. 34 coins is
BTC with leverage. Single-asset-class books cap out around 3 independent bets,
which is structurally too few for any trend or momentum strategy to work.

## And solving breadth still was not enough

| | ann | Sharpe | maxDD | growth |
|---|---|---|---|---|
| **60/40 SPY-AGG** | 8.4% | **0.74** | -34.7% | 6.3x |
| Buy & hold SPY | 11.3% | 0.61 | -55.2% | 11.6x |
| Multi-asset trend, 35 markets, 26 years | 0.2% | **0.02** | -47.8% | 1.0x |

Fully diversified systematic trend following, over 26 years, lost decisively to
two ETFs held and ignored. The 2011-2019 managed-futures drought is visible in
the data at Sharpe -0.57 over nine years.

Caveats in both directions: Yahoo `=F` series are not back-adjusted, so roll gaps
corrupt the trend signal and this understates real CTA performance (published
trend indices suggest ~0.3). And 60/40's 0.74 spans a historic bond bull market
that ended in 2022; forward-looking it is more plausibly 0.4-0.5. The ranking
does not flip either way.

## Everything tested, ranked

```
0.76  60/40 + 20% trend sleeve
0.74  60/40, held and ignored
0.61  SPY, held and ignored
0.32  crypto trend, post-bull, best-of-4 params (selection-biased)
0.19  multi-asset futures trend, 35 markets, 26 years
0.10  FX G10 time-series momentum
0.00  FX G10 cross-sectional momentum
 neg  this bot (-0.115R/trade over 5,594 trades)
```

## The only surviving finding

Trend following has value as a **diversifying sleeve**, not as a standalone
strategy. Correlation to SPY is -0.09, and it pays out precisely when a
conventional portfolio cannot — in 2022, stocks and bonds fell together, 60/40
lost 16%, and trend strategies gained 22-24%.

Blending it in (equal-risk, 26-year synthetic sleeve):

| | ann | Sharpe | maxDD |
|---|---|---|---|
| 60/40 alone | 8.43% | 0.74 | -34.7% |
| 60/40 + 20% trend | 8.63% | 0.76 | -31.4% |

**Worth roughly +0.2% to +0.8% per year**, arriving lumpily — mostly one good
year per decade while looking like dead weight in between. Measured against real
investable products (DBMF, KMLM) the 2019-2026 figure is higher (+1.8 to +2.3%/yr),
but roughly 75% of that is the single year 2022.

At $100k of capital that is $200-800 per year. It is obtainable by buying a
managed-futures ETF in an ordinary brokerage account. It does not justify
building or operating a CTA, which is the conclusion that ended this project.

## Why it stopped

The goal was steady profits. Four strategy families were tested against ~18-26
years of data and several thousand out-of-sample trades. None produced an edge.
The best-performing thing in the entire study was a diversified buy-and-hold
portfolio, which requires no edge, no code, and no bot — it pays for bearing
risk rather than for outsmarting anyone.

Continuing would have meant searching a space that had been measured as empty.

## What was actually worth having

The transferable result is not a strategy — it is the method:

1. **Measure before building.** The backtester existed for months and was never
   run. One 20-minute sweep produced 165x more evidence than four months of live
   paper trading, and answered the question definitively.
2. **Ablate.** Complexity that has never been measured against a baseline is not
   sophistication, it is unvalidated assumption. Every filtering layer here
   turned out to be worth zero.
3. **Test the dumbest version first.** Textbook parameters, no searching. If the
   simple version does not work, tuning will only manufacture an illusion.
4. **Believe the negative result.** Reaching it in a day is a far better outcome
   than reaching it in three years with real money.

## Repository layout (as archived)

```
src/broker/      OANDA v20 connector, order manager, trade logger   [sound]
src/backtest/    event-driven engine, metrics, reporter             [sound]
src/data/        loaders, historical fetcher, calendar, COT         [sound]
src/signals/     four price-action detectors + quality scorer       [no edge]
src/analysis/    confluence, regime, MTF, order book, structure     [no value measured]
src/learning/    adaptive engine, self-corrector, pair selector     [actively harmful]
deploy/launchd/  weekly scheduling, hardened .env loading           [sound]
tests/           226 tests                                          [sound]
```

The broker, backtest, data and deployment layers are reusable. The signal,
analysis and learning layers were measured as worthless and should not be
carried into anything else.
