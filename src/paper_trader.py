"""Paper trading engine — live signals on OANDA practice account.

Polls candles on a schedule, generates signals using the full strategy
engine, places paper orders via OrderManager, and feeds results back
into the learning system.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, date

from src.broker.broker_base import OrderSide, OrderStatus
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
from src.utils.formatters import format_pnl, format_pct
from src.config import (
    RISK_PER_TRADE, QUALITY_SCORE_MIN, TIMEFRAMES, TOP_PAIRS, DATA_DIR,
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
    ])
    timeframes: list[str] = field(default_factory=lambda: ["H1"])
    signal_types: list[str] = field(default_factory=lambda: [
        "reversal", "pullback", "buildup", "bos",
    ])
    min_quality_score: float = QUALITY_SCORE_MIN
    min_rr: float = 2.0
    risk_per_trade: float = RISK_PER_TRADE
    max_open_trades: int = 3
    poll_interval: int = 120  # seconds between scan cycles
    max_cycles: int = 0       # 0 = run forever
    auto_pair_selection: bool = True
    use_learning: bool = True


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

        self.state = PaperTraderState()
        self._running = False

    def start(self) -> None:
        """Connect and run the paper trading loop."""
        logger.info("=" * 60)
        logger.info("PAPER TRADER STARTING")
        logger.info("=" * 60)

        if not self.connector.connect():
            logger.error("Failed to connect to OANDA — check API key and account ID")
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

        self._running = True
        logger.info(
            "Scanning pairs: %s | Timeframes: %s | Signals: %s",
            self.config.pairs, self.config.timeframes, self.config.signal_types,
        )
        logger.info("Poll interval: %ds | Max open trades: %d",
                     self.config.poll_interval, self.config.max_open_trades)
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
            logger.info("--- New trading day: %s ---", today)

        # Sync open trades with broker
        self.order_mgr.sync_open_trades()
        self._check_closed_trades()

        # Run learning corrections periodically
        if self.config.use_learning and self.state.cycles % 10 == 0:
            self._run_corrections()

        # Select pairs
        pairs = self._get_active_pairs()

        # Scan for signals
        all_signals: list[Signal] = []
        for pair in pairs:
            for tf in self.config.timeframes:
                signals = self._scan_pair(pair, tf)
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

    def _scan_pair(self, pair: str, timeframe: str) -> list[Signal]:
        """Fetch candles and generate signals for one pair/timeframe."""
        try:
            df = self.connector.get_candles(pair, timeframe, count=CANDLE_COUNT)
        except Exception as e:
            logger.warning("Failed to fetch %s %s: %s", pair, timeframe, e)
            return []

        if len(df) < 50:
            return []

        signals = []
        enabled_types = self._get_enabled_signal_types()

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

        # Score and filter
        scored = []
        for signal in signals:
            # Apply adaptive adjustment
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

    def _check_closed_trades(self) -> None:
        """Detect trades closed by SL/TP since last sync and record them."""
        # OrderManager.sync_open_trades() already handles removing closed trades
        # and updating balance. We need to get the last known trades from
        # the trade logger and check for newly closed ones.
        pass

    def _get_active_pairs(self) -> list[str]:
        """Get the list of pairs to scan this cycle."""
        if self.pair_selector and self.config.auto_pair_selection:
            selected = self.pair_selector.select(source="paper")
            if selected:
                return selected
        return self.config.pairs

    def _get_enabled_signal_types(self) -> list[str]:
        """Get signal types not disabled by the self-corrector."""
        if self.corrector:
            return [
                st for st in self.config.signal_types
                if self.corrector.is_signal_enabled(st)
            ]
        return self.config.signal_types

    def _run_corrections(self) -> None:
        """Run the self-corrector and apply any corrections."""
        if not self.corrector:
            return

        corrections = self.corrector.evaluate(
            signal_types=self.config.signal_types,
            source="paper",
            last_n=50,
        )

        for correction in corrections:
            logger.warning("CORRECTION: %s — %s", correction.action.value, correction.detail)
            self.corrector.apply_correction(correction)

        if self.adaptive:
            self.adaptive.clear_cache()

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
        }
