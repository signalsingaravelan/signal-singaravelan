"""Main trading execution logic."""

import pytz
import exchange_calendars as xcals
import pandas as pd
import numpy as np

from datetime import datetime

from algo_trader.clients import IBKRClient, MarketDataProvider
from algo_trader.core.strategy import TradingStrategy
from algo_trader.logging import get_logger, TradeLogger
from algo_trader.utils.config import SYMBOL, TQQQ_CONTRACT_ID, MAX_PER_ORDER
from algo_trader.utils.enums import Signal


class Trader:
    """Main trader class that orchestrates trading operations."""
    
    def __init__(self):
        self.client = IBKRClient()
        self.market_data = MarketDataProvider()
        self.strategy = TradingStrategy()
        self.trade_logger = TradeLogger()
        self.logger = get_logger()

    def is_market_open(self):
        est = pytz.timezone('US/Eastern')
        current_date = datetime.now(est).date()
        nyse = xcals.get_calendar("XNYS")
        return nyse.is_session(current_date)

    def execute_trade(self) -> None:
        """Execute the main trading logic."""
        try:
            self.client.check_auth()
            account_id = self.client.get_account_id()
            
            # Initialize CloudWatch with account-specific log group
            self.logger.initialize_cloudwatch(account_id)
            self.logger.info("----------------BEGIN----------------")

            # Check if market is open today
            if not self.is_market_open():
                self.logger.info("Market is not open. Exiting.")
                return
            
            signal = self.strategy.get_signal()
            self.logger.info(f"Market signal: {signal.name}")
            
            price = self.market_data.get_price(SYMBOL)
            current_position = self.client.get_position(account_id, int(TQQQ_CONTRACT_ID))
            
            self.logger.info(f"{SYMBOL} Price: ${price:.2f}")
            self.logger.info(f"Current Position: {current_position} shares")
            
            if signal == Signal.BULLISH:
                self._handle_bullish_signal(account_id, price)
            else:
                self._handle_bearish_or_neutral_signal(account_id, current_position)
                
        except Exception as e:
            self.logger.error(f"Trade execution failed: {e}")
            raise
        finally:
            self.logger.info("-----------------END-----------------")
    
    def _handle_bullish_signal(self, account_id: str, price: float) -> None:
        """Handle bullish signal by buying the symbol."""
        available_cash = self.client.get_available_cash(account_id)
        self.logger.info(f"Available cash: ${available_cash:.2f}")
        
        if available_cash > 0:
            cash_amount = min(available_cash, MAX_PER_ORDER)
            self.logger.info(f"Placing BUY order for ${cash_amount:.2f} of {SYMBOL}")
            
            shares = cash_amount / price
            
            self.client.place_buy_order(account_id, TQQQ_CONTRACT_ID, cash_amount)
            self.trade_logger.log_trade(account_id, "Buy", SYMBOL, cash_amount, shares)
        else:
            self.logger.warning("Insufficient cash for purchase")
    
    def _handle_bearish_or_neutral_signal(self, account_id: str, current_position: float) -> None:
        """Handle bearish or neutral signal by selling the symbol."""
        if current_position > 0:
            quantity = int(current_position)
            self.logger.info(f"Placing SELL order for {quantity} shares of {SYMBOL}")
            
            price = self.market_data.get_price(SYMBOL)
            dollar_amount = quantity * price
            shares = current_position
            
            self.client.place_sell_order(account_id, TQQQ_CONTRACT_ID, quantity)
            self.trade_logger.log_trade(account_id, "Sell", SYMBOL, dollar_amount, shares)
        else:
            self.logger.info(f"No {SYMBOL} position to sell")
