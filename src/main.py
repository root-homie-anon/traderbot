"""Bot entry point - modes: backtest, paper, live."""

import argparse

from src.logger import setup_logger

logger = setup_logger()


def main():
    parser = argparse.ArgumentParser(description="PA Trading Bot")
    parser.add_argument(
        "--mode",
        choices=["backtest", "paper", "live"],
        default="backtest",
        help="Trading mode (default: backtest)",
    )
    args = parser.parse_args()

    logger.info(f"Starting bot in {args.mode} mode")

    if args.mode == "backtest":
        from src.data.data_loader import generate_sample_data
        from src.backtest import run_backtest, BacktestConfig
        from src.backtest.reporter import format_report, trade_log

        logger.info("Running backtest...")
        df = generate_sample_data(periods=2000)
        config = BacktestConfig()
        result = run_backtest(df, pair="EUR_USD", timeframe="H1", config=config)
        print(format_report(result["metrics"], result["config"]))
        print()
        print(trade_log(result["trades"]))
    elif args.mode == "paper":
        logger.info("Paper trading mode - not yet implemented")
    elif args.mode == "live":
        logger.info("Live trading mode - not yet implemented")


if __name__ == "__main__":
    main()
