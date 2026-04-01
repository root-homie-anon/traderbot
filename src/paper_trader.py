"""Paper trading engine — live signals on OANDA practice account.

Polls candles on a schedule, generates signals using the full strategy
engine, places paper orders via OrderManager, and feeds results back
into the learning system.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, date

from src.broker.broker_base import Order, OrderSide, OrderStatus, OrderType
from src.broker.oanda_connector import OandaConnector
from src.broker.order_manager import OrderManager
from src.broker.trade_logger import TradeLogger
from src.learning.performance_tracker import PerformanceTracker
from src.learning.adaptive_engine import AdaptiveEngine
from src.learning.self_corrector import SelfCorrector, ActionType
from src.learning.pair_selector import PairSelector
from src.signals.signal_base import Signal, SignalDirection
from src.signals.reversal_signal import detect_reversal_signals
from src.signals.pullback_signal import detect_pullback_signals
from src.signals.buildup_signal import detect_buildup_signals
from src.signals.bos_signal import detect_bos_signals
from src.signals.quality_scorer import score_signal
from src.analysis.confluence import calculate_confluence
from src.analysis.trend_strength import calculate_trend_strength
from src.analysis.market_structure import classify_structure
from src.analysis.regime_detector import RegimeDetector
from src.trading_sessions import get_tradeable_pairs, get_session_name
from src.utils.formatters import format_pnl, format_pct
from src.config import (
    RISK_PER_TRADE, QUALITY_SCORE_MIN, CONFLUENCE_MIN, TIMEFRAMES, TOP_PAIRS, DATA_DIR,
)

logger = logging.getLogger("pa_bot")

SIGNAL_DETECTORS = {
    "reversal": detect_reversal_signals,
    "pullback": detect_pullback_signals,
    "buildup": detect_buildup_signals,
    "bos": detect_bos_signals,
}

# How many candles to fetch for analysis
CANDLE_COUNT = 200

# Paper trade target before going live
PAPER_TRADE_TARGET = 200

# Polling interval in seconds per timeframe
POLL_INTERVALS = {
    "M15": 60,       # check every 1 min
    "H1": 120,       # check every 2 min
    "H4": 300,       # check every 5 min
    "D": 600,         # check every 10 min
}


@dataclass
class PaperTraderConfig:
    """Configuration for the paper trading engine."""

    pairs: list[str] = field(default_factory=lambda: [
        "EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "EUR_GBP",
        "USD_CAD", "NZD_USD", "EUR_JPY", "GBP_JPY",
    ])
    timeframes: list[str] = field(default_factory=lambda: ["H1"])
    signal_types: list[str] = field(default_factory=lambda: [
        "reversal", "pullback", "buildup", "bos",
    ])
    min_quality_score: float = QUALITY_SCORE_MIN
    min_rr: float = 2.0
    risk_per_trade: float = RISK_PER_TRADE
    max_open_trades: int = 5
    poll_interval: int = 120  # seconds between scan cycles
    max_cycles: int = 0       # 0 = run forever
    auto_pair_selection: bool = True
    use_learning: bool = True
    use_session_filter: bool = True


@dataclass
class PaperTraderState:
    """Runtime state of the paper trader."""

    cycles: int = 0
    signals_generated: int = 0
    orders_placed: int = 0
    orders_rejected: int = 0
    trades_closed: int = 0
    total_pnl: float = 0.0
    start_time: datetime = field(default_factory=datetime.now)
    current_day: date | None = None


class PaperTrader:
    """Live paper trading engine.

    Connects to OANDA practice, scans for signals, places paper orders,
    and tracks performance through the learning system.

    Usage:
        trader = PaperTrader()
        trader.start()  # blocks, runs until stopped
    """

    def __init__(
        self,
        config: PaperTraderConfig | None = None,
        connector: OandaConnector | None = None,
    ):
        self.config = config or PaperTraderConfig()
        self.connector = connector or OandaConnector()

        # These get initialized in start()
        self.order_mgr: OrderManager | None = None
        self.trade_logger: TradeLogger | None = None
        self.perf_tracker: PerformanceTracker | None = None
        self.adaptive: AdaptiveEngine | None = None
        self.corrector: SelfCorrector | None = None
        self.pair_selector: PairSelector | None = None

        self.regime_detector = RegimeDetector()
        self.state = PaperTraderState()
        self._running = False
        # Map order_id -> signal metadata for recording closed trades
        self._signal_meta: dict[str, dict] = {}

    def start(self) -> None:
        """Connect and run the paper trading loop."""
        logger.info("=" * 60)
        logger.info("PAPER TRADER STARTING")
        logger.info("=" * 60)

        _connect_attempts = 3
        _connect_delay = 10
        _connected = False
        for _attempt in range(1, _connect_attempts + 1):
            logger.info(
                "Connecting to OANDA (attempt %d/%d)...", _attempt, _connect_attempts,
            )
            if self.connector.connect():
                _connected = True
                break
            if _attempt < _connect_attempts:
                logger.warning(
                    "Connection failed — retrying in %ds...", _connect_delay,
                )
                time.sleep(_connect_delay)

        if not _connected:
            logger.error(
                "Failed to connect to OANDA after %d attempts — check API key and account ID",
                _connect_attempts,
            )
            return

        # Get account info
        account = self.connector.get_account_info()
        logger.info(
            "Account: %s | Balance: %.2f %s",
            "OANDA Practice", account.balance, account.currency,
        )

        # Initialize components
        self.order_mgr = OrderManager(
            broker=self.connector,
            account_balance=account.balance,
            risk_per_trade=self.config.risk_per_trade,
            max_open_trades=self.config.max_open_trades,
        )
        self.trade_logger = TradeLogger()
        self.perf_tracker = PerformanceTracker()
        self.adaptive = AdaptiveEngine(self.perf_tracker) if self.config.use_learning else None
        self.corrector = SelfCorrector(self.perf_tracker) if self.config.use_learning else None
        self.pair_selector = PairSelector(
            self.perf_tracker, max_pairs=TOP_PAIRS
        ) if self.config.auto_pair_selection else None

        # Backfill signal metadata for trades already open at the broker
        # so early TP and learning can track them
        try:
            existing = self.connector.get_open_trades()
            for t in existing:
                self._signal_meta[t.order_id] = {
                    "signal_type": "unknown",
                    "timeframe": "H1",
                    "quality_score": 0,
                    "confluence_level": 0,
                    "entry_price": t.fill_price,
                    "stop_loss": t.stop_loss,
                    "take_profit": t.take_profit,
                    "direction": t.side.value,
                    "pair": t.pair,
                }
                self.order_mgr.open_orders[t.order_id] = t
            if existing:
                logger.info("Picked up %d existing trades from broker", len(existing))
        except Exception as e:
            logger.warning("Failed to backfill existing trades: %s", e)

        # Reconcile trades that closed while the bot was offline
        self._reconcile_offline_closed_trades()

        self._running = True
        logger.info(
            "Scanning pairs: %s | Timeframes: %s | Signals: %s",
            self.config.pairs, self.config.timeframes, self.config.signal_types,
        )
        logger.info("Poll interval: %ds | Max open trades: %d | Session: %s",
                     self.config.poll_interval, self.config.max_open_trades,
                     get_session_name())
        self._log_progress()
        logger.info("-" * 60)

        try:
            self._run_loop()
        except KeyboardInterrupt:
            logger.info("Paper trader stopped by user")
        finally:
            self._shutdown()

    def stop(self) -> None:
        """Signal the trading loop to stop."""
        self._running = False

    def _reconcile_offline_closed_trades(self) -> None:
        """Record outcomes for trades that closed while the bot was offline.

        Loads all persisted signal metadata from the database, compares against
        currently open order IDs at the broker, and for any that are no longer
        open fetches the closed trade record from OANDA and writes the outcome
        to the performance tracker.  Orders still open are loaded into
        _signal_meta so live tracking continues normally.
        """
        try:
            pending_meta = self.trade_logger.load_pending_signal_meta()
        except Exception as e:
            logger.warning("Failed to load pending signal metadata: %s", e)
            return

        if not pending_meta:
            return

        open_ids = set(self.order_mgr.open_orders.keys())
        offline_closed = {oid: m for oid, m in pending_meta.items() if oid not in open_ids}
        still_open = {oid: m for oid, m in pending_meta.items() if oid in open_ids}

        # Restore in-memory meta for trades still open so _check_closed_trades
        # can pick them up during normal live operation
        for oid, meta in still_open.items():
            if oid not in self._signal_meta:
                self._signal_meta[oid] = meta

        if not offline_closed:
            return

        logger.info(
            "Reconciling %d trade(s) closed while offline", len(offline_closed),
        )

        for oid, meta in offline_closed.items():
            details = self._fetch_close_details(oid, meta.get("pair", "unknown"))
            if not details:
                continue

            try:
                self._record_closed_trade(oid, meta, details)
            except Exception as e:
                logger.warning(
                    "Failed to record offline trade %s: %s", oid, e,
                )
                continue

            logger.info(
                "OFFLINE TRADE RECONCILED: %s %s | exit=%.5f | PnL=%.2f | reason=%s",
                meta.get("direction", "").upper(), meta.get("pair", ""),
                details["exit_price"], details["realized_pnl"], details["exit_reason"],
            )

    def _run_loop(self) -> None:
        """Main polling loop."""
        while self._running:
            try:
                self._cycle()
            except Exception as e:
                logger.error("Cycle error: %s", e, exc_info=True)

            self.state.cycles += 1

            if 0 < self.config.max_cycles <= self.state.cycles:
                logger.info("Max cycles (%d) reached", self.config.max_cycles)
                self._running = False
                break

            time.sleep(self.config.poll_interval)

    def _cycle(self) -> None:
        """Run one scan-and-trade cycle."""
        now = datetime.now()

        # Daily reset
        today = now.date()
        if today != self.state.current_day:
            self.state.current_day = today
            if self.order_mgr:
                self.order_mgr.reset_daily()
                # Re-sync balance with broker to prevent drift from swaps/fees
                try:
                    account = self.connector.get_account_info()
                    old_balance = self.order_mgr.balance
                    self.order_mgr.balance = account.balance
                    if abs(old_balance - account.balance) > 0.01:
                        logger.info(
                            "Balance re-synced: %.2f → %.2f (drift: %+.2f)",
                            old_balance, account.balance,
                            account.balance - old_balance,
                        )
                except Exception as e:
                    logger.warning("Failed to re-sync balance: %s", e)
            logger.info("--- New trading day: %s ---", today)

        # Sync open trades and record any that closed
        self._check_closed_trades()

        # Resolve current session once per cycle so all downstream calls agree
        current_session = get_session_name()

        # Run learning corrections periodically
        if self.config.use_learning and self.state.cycles % 10 == 0:
            self._run_corrections(session=current_session)

        # Advance the adaptive engine cache every cycle so stale entries are
        # evicted based on TTL rather than only on the 10-cycle correction flush
        if self.config.use_learning and self.adaptive:
            self.adaptive.advance_cycle()

        # Select pairs
        pairs = self._get_active_pairs(session=current_session)

        # Scan for signals
        all_signals: list[Signal] = []
        for pair in pairs:
            for tf in self.config.timeframes:
                signals = self._scan_pair(pair, tf, session=current_session)
                all_signals.extend(signals)

        if not all_signals:
            return

        # Sort by quality score and try to place
        all_signals.sort(key=lambda s: s.quality_score, reverse=True)
        logger.info(
            "Cycle %d: %d signals found across %d pairs",
            self.state.cycles, len(all_signals), len(pairs),
        )

        for signal in all_signals:
            if not self._running:
                break
            self._try_place_order(signal)

    def _scan_pair(
        self, pair: str, timeframe: str, session: str | None = None
    ) -> list[Signal]:
        """Fetch candles and generate signals for one pair/timeframe."""
        try:
            df = self.connector.get_candles(pair, timeframe, count=CANDLE_COUNT)
        except Exception as e:
            logger.warning("Failed to fetch %s %s: %s", pair, timeframe, e)
            return []

        if len(df) < 50:
            return []

        regime = self.regime_detector.detect_regime(df)
        logger.debug(
            "Regime %s %s: %s (ADX=%.1f)",
            pair, timeframe, regime.regime_type, regime.adx_value,
        )

        signals = []
        enabled_types = self._get_enabled_signal_types(session=session)

        for sig_type in enabled_types:
            detector = SIGNAL_DETECTORS.get(sig_type)
            if not detector:
                continue
            try:
                found = detector(
                    df, pair=pair, timeframe=timeframe,
                    min_rr=self.config.min_rr,
                )
                signals.extend(found)
            except Exception as e:
                logger.debug("Detector %s failed on %s %s: %s",
                             sig_type, pair, timeframe, e)

        # Score signals with full 6-factor quality scorer
        trend = calculate_trend_strength(df)
        structure = classify_structure(df)

        scored = []
        for signal in signals:
            # Skip signals with insufficient confluence
            if signal.confluence_level < CONFLUENCE_MIN:
                continue

            # Get performance-based win rates for quality scoring.
            # Prefer session-scoped stats; fall back to global if data is thin.
            live_wr = None
            if self.perf_tracker:
                stats = self.perf_tracker.get_stats(
                    pair=pair, signal_type=signal.signal_type.value,
                    source="paper", last_n=50, session=session,
                    weight_type="exponential",
                )
                if stats.total_trades < 5 and session:
                    stats = self.perf_tracker.get_stats(
                        pair=pair, signal_type=signal.signal_type.value,
                        source="paper", last_n=50, weight_type="exponential",
                    )
                if stats.total_trades >= 5:
                    live_wr = stats.win_rate

            # Calculate proper 6-factor quality score
            direction = "bullish" if signal.direction == SignalDirection.BUY else "bearish"
            confluence = calculate_confluence(df, direction=direction)
            breakdown = score_signal(
                signal,
                confluence=confluence,
                trend=trend,
                structure=structure,
                live_win_rate=live_wr,
            )
            signal.quality_score = breakdown.total_score

            # Apply regime multiplier based on current market state
            regime_multiplier = regime.signal_multipliers.get(
                signal.signal_type.value, 1.0
            )
            signal.quality_score *= regime_multiplier

            # Apply adaptive adjustment on top
            if self.adaptive:
                adj = self.adaptive.get_adjustment(
                    signal.signal_type.value, pair, timeframe, source="paper",
                )
                signal.quality_score *= adj.multiplier

            if signal.quality_score >= self.config.min_quality_score:
                scored.append(signal)

        self.state.signals_generated += len(scored)
        return scored

    def _try_place_order(self, signal: Signal) -> None:
        """Attempt to place a paper order for a signal."""
        result = self.order_mgr.submit_signal(signal)

        if result.success:
            self.state.orders_placed += 1
            self.trade_logger.log_order(result.order, event="placed")
            meta = {
                "signal_type": signal.signal_type.value,
                "timeframe": signal.timeframe,
                "quality_score": signal.quality_score,
                "confluence_level": getattr(signal, "confluence_level", 0),
                "entry_price": signal.entry_price,
                "stop_loss": signal.stop_loss,
                "take_profit": signal.take_profit,
                "direction": signal.direction.value,
                "pair": signal.pair,
            }
            self._signal_meta[result.order.order_id] = meta
            self.trade_logger.save_signal_meta(result.order.order_id, meta)
            logger.info(
                "ORDER PLACED: %s %s %s | entry=%.5f sl=%.5f tp=%.5f | QS=%.1f",
                signal.direction.value.upper(),
                signal.pair,
                signal.timeframe,
                signal.entry_price,
                signal.stop_loss,
                signal.take_profit,
                signal.quality_score,
            )
        else:
            self.state.orders_rejected += 1
            logger.debug("Order rejected: %s — %s", signal.pair, result.reason)

    def _fetch_close_details(self, oid: str, pair: str) -> dict | None:
        """Fetch close details for a trade from OANDA.

        Returns dict with realized_pnl, exit_price, exit_reason, or None on failure.
        """
        try:
            trades_resp = self.connector._request(
                "GET",
                f"/v3/accounts/{self.connector.account_id}/trades/{oid}",
            )
            trade_data = trades_resp.get("trade", {})
            realized_pnl = float(trade_data.get("realizedPL", 0))
            exit_price = float(trade_data.get("averageClosePrice", 0))
        except Exception as e:
            logger.warning(
                "Failed to fetch close details for trade %s (%s): %s", oid, pair, e,
            )
            return None

        if exit_price == 0.0:
            logger.warning("Trade %s (%s) returned no averageClosePrice", oid, pair)
            return None

        # Determine exit reason from OANDA order states
        sl_order = trade_data.get("stopLossOrder", {})
        tp_order = trade_data.get("takeProfitOrder", {})
        sl_state = sl_order.get("state", "")
        tp_state = tp_order.get("state", "")

        if tp_state in ("FILLED", "TRIGGERED"):
            exit_reason = "take_profit"
        elif sl_state in ("FILLED", "TRIGGERED"):
            exit_reason = "stop_loss"
        else:
            exit_reason = "closed"

        return {
            "realized_pnl": realized_pnl,
            "exit_price": exit_price,
            "exit_reason": exit_reason,
        }

    def _record_closed_trade(self, oid: str, meta: dict, details: dict) -> None:
        """Record a closed trade to the performance tracker and trade logger."""
        exit_price = details["exit_price"]
        realized_pnl = details["realized_pnl"]
        exit_reason = details["exit_reason"]

        self.state.total_pnl += realized_pnl
        risk_amount = abs(meta["entry_price"] - meta["stop_loss"])

        self.perf_tracker.record_trade({
            "timestamp": datetime.now().isoformat(),
            "pair": meta["pair"],
            "signal_type": meta["signal_type"],
            "timeframe": meta["timeframe"],
            "direction": meta["direction"],
            "entry_price": meta["entry_price"],
            "exit_price": exit_price,
            "stop_loss": meta["stop_loss"],
            "take_profit": meta["take_profit"],
            "pnl": realized_pnl,
            "risk_amount": risk_amount,
            "exit_reason": exit_reason,
            "quality_score": meta["quality_score"],
            "confluence_level": meta["confluence_level"],
        }, source="paper")

        self.trade_logger.delete_signal_meta(oid)

        side = OrderSide.BUY if meta["direction"] == "buy" else OrderSide.SELL
        closed_order = Order(
            order_id=oid,
            pair=meta["pair"],
            side=side,
            order_type=OrderType.MARKET,
            units=0,
            fill_price=exit_price,
            stop_loss=meta["stop_loss"],
            take_profit=meta["take_profit"],
            status=OrderStatus.FILLED,
            pnl=realized_pnl,
        )
        self.trade_logger.log_order(closed_order, event="closed")

        logger.info(
            "TRADE CLOSED: %s %s | exit=%.5f | PnL=%.2f | reason=%s",
            meta["direction"].upper(), meta["pair"],
            exit_price, realized_pnl, exit_reason,
        )
        self._log_progress()

    def _check_closed_trades(self) -> None:
        """Detect trades closed by SL/TP since last sync and record them."""
        # Snapshot order IDs before sync
        prev_ids = set(self.order_mgr.open_orders.keys())

        # sync_open_trades removes orders that are no longer open at the broker
        self.order_mgr.sync_open_trades()

        # Detect which orders disappeared (closed by SL/TP)
        current_ids = set(self.order_mgr.open_orders.keys())
        closed_ids = prev_ids - current_ids

        for oid in closed_ids:
            self.state.trades_closed += 1
            meta = self._signal_meta.pop(oid, None)
            if not meta:
                logger.info("Trade %s closed (no signal metadata)", oid)
                continue

            details = self._fetch_close_details(oid, meta.get("pair", "unknown"))
            if not details:
                continue

            self._record_closed_trade(oid, meta, details)

    def _get_active_pairs(self, session: str | None = None) -> list[str]:
        """Get the list of pairs to scan this cycle.

        Filters by market session first, then uses performance-based
        selection if enough data is available.  When ``session`` is given,
        pair selection ranks using session-scoped performance data.
        """
        base_pairs = self.config.pairs

        # Filter by trading session if enabled
        if self.config.use_session_filter:
            base_pairs = get_tradeable_pairs(base_pairs)
            if not base_pairs:
                logger.debug("No pairs in session — skipping cycle")
                return []

        if self.pair_selector and self.config.auto_pair_selection:
            stats = self.perf_tracker.get_stats(source="paper")
            if stats.total_trades >= self.pair_selector.min_trades * 2:
                selected = self.pair_selector.select(
                    source="paper", session=session
                )
                if selected:
                    if self.config.use_session_filter:
                        return [p for p in selected if p in base_pairs]
                    return selected

        return base_pairs

    def _get_enabled_signal_types(self, session: str | None = None) -> list[str]:
        """Get signal types not disabled by the self-corrector.

        When ``session`` is provided, a signal type is excluded if it is
        disabled either globally or specifically for that session.
        """
        if self.corrector:
            return [
                st for st in self.config.signal_types
                if self.corrector.is_signal_enabled(st, session=session)
            ]
        return self.config.signal_types

    def _run_corrections(self, session: str | None = None) -> None:
        """Run the self-corrector and apply any corrections.

        When ``session`` is provided, corrections are evaluated against
        session-scoped stats and applied as per-session disables.
        """
        if not self.corrector:
            return

        corrections = self.corrector.evaluate(
            signal_types=self.config.signal_types,
            source="paper",
            last_n=50,
            session=session,
        )

        for correction in corrections:
            logger.warning("CORRECTION: %s — %s", correction.action.value, correction.detail)
            self.corrector.apply_correction(correction)

    def _log_progress(self) -> None:
        """Log paper trade progress toward the 200-trade target."""
        try:
            stats = self.perf_tracker.get_paper_trade_count()
            total = stats["total"]
            wins = stats["wins"]
            pnl = stats["pnl"]
            pct = total / PAPER_TRADE_TARGET * 100
            win_rate = wins / total * 100 if total > 0 else 0
            logger.info(
                "PROGRESS: %d/%d trades (%.0f%%) | Win rate: %.0f%% | PnL: %s",
                total, PAPER_TRADE_TARGET, pct, win_rate, format_pnl(pnl),
            )
        except Exception as e:
            logger.warning("Failed to log progress: %s", e)

    def _shutdown(self) -> None:
        """Clean shutdown — log summary and disconnect."""
        elapsed = (datetime.now() - self.state.start_time).total_seconds()
        hours = elapsed / 3600

        logger.info("=" * 60)
        logger.info("PAPER TRADER SUMMARY")
        logger.info("-" * 60)
        logger.info("Runtime: %.1f hours | Cycles: %d", hours, self.state.cycles)
        logger.info("Signals: %d | Orders placed: %d | Rejected: %d",
                     self.state.signals_generated, self.state.orders_placed,
                     self.state.orders_rejected)
        logger.info("PnL: %s", format_pnl(self.state.total_pnl))

        if self.order_mgr and self.order_mgr.open_orders:
            logger.info("Open trades at shutdown: %d", len(self.order_mgr.open_orders))

        logger.info("=" * 60)

        self.connector.disconnect()

    def get_status(self) -> dict:
        """Get current status for display or API."""
        open_count = len(self.order_mgr.open_orders) if self.order_mgr else 0
        progress = self.perf_tracker.get_paper_trade_count() if self.perf_tracker else {}
        return {
            "running": self._running,
            "cycles": self.state.cycles,
            "signals_generated": self.state.signals_generated,
            "orders_placed": self.state.orders_placed,
            "orders_rejected": self.state.orders_rejected,
            "open_trades": open_count,
            "total_pnl": self.state.total_pnl,
            "balance": self.order_mgr.balance if self.order_mgr else 0,
            "uptime_seconds": (datetime.now() - self.state.start_time).total_seconds(),
            "active_pairs": self._get_active_pairs(),
            "enabled_signals": self._get_enabled_signal_types(),
            "paper_trade_target": PAPER_TRADE_TARGET,
            "paper_trades_completed": progress.get("total", 0),
            "paper_trade_progress_pct": round(
                progress.get("total", 0) / PAPER_TRADE_TARGET * 100, 1
            ),
        }
