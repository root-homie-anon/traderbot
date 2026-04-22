"""Bot entry point - modes: backtest, paper, live."""

import argparse
import signal

from src.logger import setup_logger

logger = setup_logger()

_shutdown_requested = False


def _handle_signal(signum: int, frame) -> None:  # type: ignore[type-arg]
    global _shutdown_requested
    _shutdown_requested = True
    logger.info("Shutdown signal received (%s) — stopping after current cycle", signum)


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


def main():
    parser = argparse.ArgumentParser(description="PA Trading Bot")
    parser.add_argument(
        "--mode",
        choices=["backtest", "paper", "live"],
        default="backtest",
        help="Trading mode (default: backtest)",
    )
    parser.add_argument(
        "--pairs",
        nargs="+",
        default=None,
        help="Pairs to trade (e.g. EUR_USD GBP_USD)",
    )
    parser.add_argument(
        "--timeframes",
        nargs="+",
        default=None,
        help="Timeframes to scan (e.g. H1 H4)",
    )
    parser.add_argument(
        "--max-trades",
        type=int,
        default=5,
        help="Max simultaneous open trades (default: 5)",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=120,
        help="Seconds between scan cycles in paper mode (default: 120)",
    )
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=0,
        help="Stop after N cycles, 0 = run forever (default: 0)",
    )
    args = parser.parse_args()

    logger.info(f"Starting bot in {args.mode} mode")

    if args.mode == "backtest":
        _run_backtest()
    elif args.mode == "paper":
        _run_paper(args)
    elif args.mode == "live":
        logger.info("Live trading mode - not yet implemented")


def _run_backtest():
    from src.data.data_loader import generate_sample_data, load_pair
    from src.backtest import run_backtest, BacktestConfig
    from src.backtest.reporter import format_report, trade_log

    pair = "EUR_USD"
    timeframe = "H1"

    logger.info("Running backtest...")

    try:
        df = load_pair(pair, timeframe)
        logger.info("Loaded real historical data: %d bars", len(df))
    except FileNotFoundError:
        logger.warning(
            "No historical CSV found for %s %s — falling back to synthetic data. "
            "Run `python3 -m src.data.run_fetch` to download real data.",
            pair,
            timeframe,
        )
        df = generate_sample_data(periods=2000)

    config = BacktestConfig()
    result = run_backtest(df, pair=pair, timeframe=timeframe, config=config)
    print(format_report(result["metrics"], result["config"]))
    print()
    print(trade_log(result["trades"]))


def _run_paper(args):
    from src.paper_trader import PaperTrader, PaperTraderConfig

    config = PaperTraderConfig(
        max_open_trades=args.max_trades,
        poll_interval=args.poll_interval,
        max_cycles=args.max_cycles,
    )

    if args.pairs:
        from src.utils.validators import validate_pair
        for p in args.pairs:
            if not validate_pair(p):
                logger.error("Invalid pair format: %s (expected XXX_YYY)", p)
                return
        config.pairs = args.pairs
    if args.timeframes:
        config.timeframes = args.timeframes

    trader = PaperTrader(config=config)

    # Wire SIGTERM/SIGINT directly to trader.stop() so the bot exits cleanly
    # after the current cycle rather than ignoring the signal.
    # The module-level _shutdown_requested flag is kept for informational logging
    # but is not sufficient on its own — trader._running must be cleared.
    def _handle_paper_signal(signum: int, frame) -> None:  # type: ignore[type-arg]
        global _shutdown_requested
        _shutdown_requested = True
        logger.info("Shutdown signal received (%s) — stopping after current cycle", signum)
        trader.stop()

    signal.signal(signal.SIGTERM, _handle_paper_signal)
    signal.signal(signal.SIGINT, _handle_paper_signal)

    try:
        trader.start()
    except Exception as e:
        logger.critical("Unhandled exception in paper trader: %s", e, exc_info=True)
        raise
    finally:
        if trader._running:
            trader._shutdown()


if __name__ == "__main__":
    main()
