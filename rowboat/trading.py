"""
Trend-following stragedy:
- If price breaks above the highest high of the last {entry} bars, buy {each_trade} of the account balance.
- SL is the lowest low of the last {exit} bars.
- Once SL is reached, close the position and open a new position in the opposite direction.
- If trend doesn't change in {enter_more_after_bars}, open a new position in the same direction regarding to the
  {max_trades_per_direction} limit.
- Vice versa for short positions.
"""

import time
import logging
from typing import Literal, Tuple
from decimal import Decimal

from binance.um_futures import UMFutures

from .config import Configuration


def get_entry_exit_price(
    symbol: str, rest_client: UMFutures, entry_int: int, exit_int: int, interval: str = "1d"
) -> Tuple[Decimal, Decimal, Decimal, Decimal]:
    "Returns (long_entry, long_exit, short_entry, short_exit)"
    bars_to_fetch = max(entry_int, exit_int) + 1  # add 1 to omit latest bar
    bars = rest_client.mark_price_klines(
        symbol=symbol, interval=interval, limit=bars_to_fetch
    )
    # Response example:
    # [
    #   [
    #     1591256460000,          // Open time
    #     "9653.29201333",        // Open
    #     "9654.56401333",        // High
    #     "9653.07367333",        // Low
    #     "9653.07367333",        // Close (or latest price)
    #     "0  ",                  // Ignore
    #     1591256519999,          // Close time
    #     "0",                    // Ignore
    #     60,                     // Ignore
    #     "0",                    // Ignore
    #     "0",                    // Ignore
    #     "0"                     // Ignore
    #   ]
    # ]
    long_entry = max(Decimal(bar[2]) for bar in bars[-entry_int - 1 : -1])
    long_exit = min(Decimal(bar[3]) for bar in bars[-exit_int - 1 : -1])
    short_entry = min(Decimal(bar[3]) for bar in bars[-entry_int - 1 : -1])
    short_exit = max(Decimal(bar[2]) for bar in bars[-exit_int - 1 : -1])
    return long_entry, long_exit, short_entry, short_exit


Direction = Literal["LONG", "SHORT", "NONE"]


def infer_position(position_dict) -> Tuple[Direction, Decimal]:
    """
    Since the program itself doesn't hold any state, it needs to infer the current position from the account info.
    Returns: (direction, investment in USDT)
    """
    amount = Decimal(position_dict["positionAmt"])  # Calculated in COIN

    if amount == 0:
        return "NONE", Decimal(0)
    if amount > 0:
        return "LONG", Decimal(position_dict["initialMargin"])
    return "SHORT", Decimal(position_dict["initialMargin"])


# TODO: Refactor this function
# TODO: enter_more_after_break_bars
def follower(symbol: str, rest_client: UMFutures, config: Configuration):
    """
    Poll the API once per 15s and make trading decisions.
    Only LONG & SHORT actions need manual intervention. In the system it is always guarantee that position is closed
      before opening a new position in either direction.
    """
    entry = config.entry
    exit = config.exit
    each_trade = config.each_trade
    max_position = config.max_per_asset  # Portion of the total account balance
    interval = config.interval
    logger = logging.getLogger(symbol)
    info = rest_client.exchange_info()
    symbol_info = next(
        (s for s in info["symbols"] if s["symbol"] == symbol), None
    )
    if symbol_info is None:
        logger.error("Symbol not found in exchange info.")
        return
    price_percision = int(symbol_info["pricePrecision"])  # Percision: 10e-x
    qty_percision = int(symbol_info["quantityPrecision"])  # Percision: 10e-x
    logger.debug(symbol_info)
    # Set leverage to 1x
    rest_client.change_leverage(symbol=symbol, leverage=1)
    logger.info("Leverage set to 1x.")
    while True:
        long_entry, long_exit, short_entry, short_exit = get_entry_exit_price(
            symbol, rest_client, entry, exit, interval
        )
        long_entry = round(long_entry, price_percision)
        long_exit = round(long_exit, price_percision)
        short_entry = round(short_entry, price_percision)
        short_exit = round(short_exit, price_percision)
        current_mark_price = Decimal(
            rest_client.mark_price(symbol=symbol)["markPrice"]
        )
        logger.info(
            "Long entry: %f, long exit: %f, short entry: %f, short exit: %f, current mark price: %f",
            long_entry,
            long_exit,
            short_entry,
            short_exit,
            current_mark_price,
        )
        account = rest_client.account()
        position = next(
            (p for p in account["positions"] if p["symbol"] == symbol), None
        )
        if position is None:
            logger.error("Symbol not found in account positions.")
            break
        logger.debug(position)
        direction, investment = infer_position(position)
        position_qty = position["positionAmt"]  # Not converted in order to avoid floating point errors
        if position_qty[0] == '-':
            position_qty = position_qty[1:]
        total_balance = float(account["totalWalletBalance"])
        avaliable_balance = float(account["availableBalance"])
        can_trade = investment < max_position * total_balance
        each_trade_usdt = Decimal(each_trade * avaliable_balance)
        open_qty = each_trade_usdt / current_mark_price
        open_qty = round(open_qty, qty_percision)
        match direction:
            case "LONG":
                # In edge cases where the price is already below SL, close the position manually.
                if current_mark_price < long_exit:
                    trade_params = {
                        "symbol": symbol,
                        "side": "SELL",
                        "positionSide": "LONG",
                        "type": "MARKET",
                        "quantity": position_qty,
                    }
                    logger.info(trade_params)
                    rest_client.new_order(**trade_params)
                    logger.warning("SL reached. Position closed.")
                    continue
                # Cancel & Set new SL for current position
                rest_client.cancel_open_orders(symbol=symbol)
                trade_params = {
                    "symbol": symbol,
                    "side": "SELL",
                    "type": "STOP_MARKET",
                    "stopPrice": long_exit,
                    "closePosition": True,
                }
                logger.info(trade_params)
                rest_client.new_order(**trade_params)
                logger.info("SL updated.")
            case "SHORT":
                # In edge cases where the price is already above SL, close the position manually.
                if current_mark_price > short_exit:
                    trade_params = {
                        "symbol": symbol,
                        "side": "BUY",
                        "type": "MARKET",
                        "quantity": position_qty,
                    }
                    logger.info(trade_params)
                    rest_client.new_order(**trade_params)
                    logger.warning("SL reached. Position closed.")
                    continue
                # Cancel & Set new SL for current position
                rest_client.cancel_open_orders(symbol=symbol)
                trade_params = {
                    "symbol": symbol,
                    "side": "BUY",
                    "type": "STOP_MARKET",
                    "stopPrice": short_exit,
                    "closePosition": True,
                }
                rest_client.new_order(**trade_params)
                logger.info("SL updated.")
            case "NONE":
                # Ready to enter a new position
                # Cancel & Set Stop Market orders
                rest_client.cancel_open_orders(symbol=symbol)
                long_entry_stop_market_params = {
                    "symbol": symbol,
                    "side": "BUY",
                    "type": "STOP_MARKET",
                    "stopPrice": long_entry,
                    "quantity": open_qty,
                }
                short_entry_stop_market_params = {
                    "symbol": symbol,
                    "side": "SELL",
                    "type": "STOP_MARKET",
                    "stopPrice": short_entry,
                    "quantity": open_qty,
                }
                logger.debug(long_entry_stop_market_params)
                logger.debug(short_entry_stop_market_params)
                rest_client.new_order(**long_entry_stop_market_params)
                rest_client.new_order(**short_entry_stop_market_params)
                logger.info("Orders updated.")
        time.sleep(15)
