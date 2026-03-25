"""Logging setup for the trading bot.

Logs go to stdout only. When running under systemd, the service unit
redirects stdout/stderr to logs/bot.log via StandardOutput=append:,
so a Python FileHandler would duplicate every line.
"""

import logging


def setup_logger(name="pa_bot", level=logging.INFO):
    """Configure and return a logger instance."""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        ch = logging.StreamHandler()
        ch.setLevel(level)

        formatter = logging.Formatter(
            "%(asctime)s | %(name)s | %(levelname)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        ch.setFormatter(formatter)
        logger.addHandler(ch)

    return logger
