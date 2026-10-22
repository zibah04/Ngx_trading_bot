"""
NGX Algorithmic Trading Bot - Main CLI Entry Point
Executes the trading engine with structured logging and graceful signal handling.

Usage:
    python main.py --broker mock
    python main.py --broker cardinalstone --api-key YOUR_KEY --account CS-12345
"""

import argparse
import asyncio
import logging
import os
import signal

from python_bot.config import load_config, DEFAULT_CONFIG_DICT
from python_bot.broker_base import BaseBroker
from python_bot.mock_broker import MockBroker
from python_bot.cardinalstone_broker import CardinalStoneBroker
from python_bot.cowrywise_broker import CowrywiseBroker
from python_bot.database import TradingDatabase
from python_bot.bot_engine import NGXQuantTradingEngine


def setup_logger(verbose: bool = False) -> logging.Logger:
    level = logging.DEBUG if verbose else logging.INFO
    log_format = "%(asctime)s [%(levelname)s] (%(name)s) %(message)s"
    logging.basicConfig(level=level, format=log_format, datefmt="%Y-%m-%d %H:%M:%S")
    return logging.getLogger("ngx_bot")


def build_broker(broker_type: str, args: argparse.Namespace) -> BaseBroker:
    broker_type = broker_type.lower()
    if broker_type == "mock":
        return MockBroker(initial_cash_naira=args.initial_cash)
    elif broker_type == "cardinalstone":
        if not args.enable_live_trading:
            raise ValueError("Live trading is disabled. Pass --enable-live-trading only after broker verification.")
        if not args.api_key or not args.api_secret or not args.account:
            raise ValueError("CardinalStone requires NGX_API_KEY, NGX_API_SECRET, and NGX_ACCOUNT.")
        return CardinalStoneBroker(
            api_key=args.api_key,
            api_secret=args.api_secret,
            account_number=args.account,
            cscs_number=args.cscs,
        )
    elif broker_type == "cowrywise":
        if not args.enable_live_trading:
            raise ValueError("Live trading is disabled. Pass --enable-live-trading only after broker verification.")
        if not args.api_key or not args.account:
            raise ValueError("Cowrywise requires NGX_API_KEY and NGX_ACCOUNT.")
        return CowrywiseBroker(api_key=args.api_key, account_id=args.account)
    raise ValueError(f"Unknown broker type: {broker_type}")


async def async_main(args: argparse.Namespace) -> None:
    logger = setup_logger(args.verbose)
    logger.info("🇳🇬 Initializing NGX Quant Trading Engine (Python 3.11+ asyncio)")

    config = load_config(DEFAULT_CONFIG_DICT)
    if args.db_path:
        config.safety.database_path = args.db_path

    broker = build_broker(args.broker, args)
    db = TradingDatabase(db_path=config.safety.database_path)
    engine = NGXQuantTradingEngine(config=config, broker=broker, database=db)

    loop = asyncio.get_running_loop()

    def handle_shutdown_signal():
        logger.warning("Received shutdown signal. Initiating graceful cleanup...")
        asyncio.create_task(engine.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_shutdown_signal)
        except NotImplementedError:
            pass

    try:
        await engine.start()
    except asyncio.CancelledError:
        logger.info("Engine cancelled.")
    finally:
        await engine.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="NGX Algorithmic Trading Bot")
    parser.add_argument("--broker", choices=["mock", "cardinalstone", "cowrywise"], default="mock")
    parser.add_argument("--api-key", default=os.getenv("NGX_API_KEY"))
    parser.add_argument("--api-secret", default=os.getenv("NGX_API_SECRET"))
    parser.add_argument("--account", default=os.getenv("NGX_ACCOUNT"))
    parser.add_argument("--cscs", default=os.getenv("NGX_CSCS_NUMBER"))
    parser.add_argument(
        "--enable-live-trading",
        action="store_true",
        help="Explicitly allow live broker adapters after API and sandbox verification.",
    )
    parser.add_argument("--initial-cash", type=float, default=2_000_000.0)
    parser.add_argument("--db-path", default=os.getenv("NGX_DATABASE_PATH", "data/ngx_trading_bot.db"))
    parser.add_argument("--verbose", action="store_true")

    args = parser.parse_args()
    try:
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        print(" Shutdown complete.")


if __name__ == "__main__":
    main()
