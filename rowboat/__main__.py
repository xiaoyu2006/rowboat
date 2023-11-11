"""Main entry point for the bot."""

import argparse
import configparser
import os
import sys
import logging
import threading
from rich.logging import RichHandler

from binance.um_futures import UMFutures

from . import __version__
from .trading import follower
from .config import Configuration

LOGGER = logging.getLogger("rowboat")


def process_config(config_file) -> Configuration:
    if not os.path.exists(config_file):
        config = configparser.ConfigParser()
        config["connection"] = {
            "api_key": "<YOUR API KEY>",
            "api_secret": "<YOUR API SECRET>",
            "testnet": "True",
        }
        config["trading"] = {
            "symbols": "BTCUSDT, ETHUSDT",
            "entry_bars": "20",
            "exit_bars": "10",
            "each_trade": "0.05",
            "enter_more_after_break_bars": "8",
            "max_per_symbol": "0.5",
            "interval": "1d",
        }
        with open(config_file, "w", encoding="utf-8") as f:
            config.write(f)
        LOGGER.info("Config file created at %s.", config_file)
        sys.exit(1)
    LOGGER.info("Using config file at %s.", config_file)
    with open(config_file, "r", encoding="utf-8") as config:
        config_content = config.read()
    config = configparser.ConfigParser()
    config.read_string(config_content)
    return Configuration(config)


def start_trading(config: Configuration):
    client = UMFutures(config.api_key, config.api_secret, base_url=config.rest_endpoint)
    account = client.account()
    exchange_info = client.exchange_info()
    LOGGER.debug({i: account[i] for i in account if i != "positions"})
    LOGGER.debug({i: exchange_info[i] for i in exchange_info if i != "symbols"})
    threads = []
    for s in config.symbols:
        t = threading.Thread(
            target=follower,
            args=(s, client, config),
            daemon=True,
        )
        t.start()
        threads.append(t)
    for t in threads:
        t.join()


def main():
    """Main entry point for the bot."""
    parser = argparse.ArgumentParser(description="Binance trend-following trading bot.")
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "-c", "--config", help="path to config file", default="rowboat.ini"
    )
    parser.add_argument("-l", "--logging-level", help="logging level", default="INFO")
    args = parser.parse_args()
    logging.basicConfig(
        level=args.logging_level,
        format="[%(name)s] :: %(message)s",
        datefmt="[%X]",
        handlers=[RichHandler()],
    )
    config = process_config(args.config)
    start_trading(config)
