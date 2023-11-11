"""Configuration format."""

import configparser


class Configuration:
    def __init__(self, config: configparser.ConfigParser) -> None:
        self.api_key: str = config["connection"]["api_key"]
        self.api_secret: str = config["connection"]["api_secret"]
        if config["connection"]["testnet"] == "True":
            self.ws_endpoint: str = "wss://stream.binancefuture.com"
            self.rest_endpoint: str = "https://testnet.binancefuture.com"
        else:
            self.ws_endpoint: str = "wss://fstream.binance.com"
            self.rest_endpoint: str = "https://fapi.binance.com"
        self.symbols: list[str] = [
            symbol.strip() for symbol in config["trading"]["symbols"].split(",")
        ]
        self.entry: int = int(config["trading"]["entry_bars"])
        self.exit: int = int(config["trading"]["exit_bars"])
        self.each_trade: float = float(config["trading"]["each_trade"])  # Portion of the total account balance
        self.max_per_symbol: float = float(
            config["trading"]["max_per_symbol"]
        )  # Portion of the total account balance
        self.enter_more_after_break_bars: int = int(
            config["trading"]["enter_more_after_break_bars"]
        )
        self.interval: str = config["trading"]["interval"]
