"""Main trading execution logic."""

from algo_trader.clients import IBKRClient, OrderRejectionError
from algo_trader.core.strategy import TradingStrategy
from algo_trader.logging import get_logger, TradeLogger
from algo_trader.models import Trade, Signal, Severity
from algo_trader.notifications import NotificationService
from algo_trader.utils.config import SYMBOL, COMMISSION_TYPE

# Trading constants
MIN_CASH_THRESHOLD = 5.0  # Minimum cash required to place a trade
CASH_BUFFER = 1.0         # Cash buffer to prevent overdraft

# IBKR Commission rates
TIERED_RATE_PER_SHARE = 0.0035    # $0.0035 per share
TIERED_MIN_COMMISSION = 0.35      # Minimum per order
TIERED_MAX_COMMISSION_PCT = 0.01  # Max 1% of trade value

FIXED_RATE_PER_SHARE = 0.005      # $0.005 per share  
FIXED_MIN_COMMISSION = 1.00       # Minimum per order


class Trader:
    """Main trader class that orchestrates trading operations."""
    
    def __init__(self):
        self.client = IBKRClient()
        self.strategy = TradingStrategy()
        self.trade_logger = TradeLogger()
        self.logger = get_logger()
        self.notifications = NotificationService()
        self.account_id = ''

    def execute_trade(self) -> None:
        """Execute the main trading logic."""
        try:
            # Initialize IBKR Client
            self.client.initialize()
            self.account_id = self.client.get_account_id()

            # Initialize CloudWatch with account-specific log group
            self.logger.initialize_cloudwatch(self.account_id)
            self.logger.info("----------------BEGIN----------------")

            signal = self.strategy.get_signal(self.account_id)
            contract_id = self.client.get_contract_id(SYMBOL)
            price = self.client.get_price(contract_id)
            current_position = self.client.get_position(self.account_id, contract_id)
            account_balance = self.client.get_account_balance(self.account_id)

            self.logger.info("-------------------------------------")
            self.logger.info(f"{SYMBOL} Price: ${price:.2f}")
            self.logger.info(f"Current Position: {current_position} shares")
            self.logger.info(f"Account Balance: ${account_balance:,.2f}")

            self.notifications.send_notification(self.account_id, Severity.INFO, f"Account Balance: ${account_balance:,.2f}")
            self.client.get_performance(self.account_id, self.notifications)

            if signal == Signal.BULLISH:
                self._handle_bullish_signal(self.account_id, contract_id, price)
            elif signal == Signal.BEARISH or signal == Signal.NEUTRAL:
                self._handle_bearish_or_neutral_signal(self.account_id, contract_id, price, current_position)
            elif signal == Signal.CLOSED:
                self.logger.info("Market is closed - no trading action taken")
            else:
                self.logger.warning(f"Unknown signal received: {signal}")

        except Exception as e:
            self.logger.error(f"Trade execution failed: {e}")
            self.notifications.send_notification(self.account_id, Severity.ERROR, f"Trade execution failed: {e}")
        finally:
            self.logger.info("-----------------END-----------------")
    
    def _handle_bullish_signal(self, account_id: str, contract_id: int, price: float) -> None:
        """Handle bullish signal by buying the symbol."""

        available_cash = self.client.get_available_cash(account_id)
        self.logger.info(f"Available Cash: ${available_cash:.2f}")
        
        if available_cash > MIN_CASH_THRESHOLD:
            quantity = available_cash / price
            commission = self._get_ibkr_commission(quantity, price, COMMISSION_TYPE)
            amount = available_cash - commission - CASH_BUFFER
            
            self.logger.info(f"Commission Estimate: ${commission:.2f}")
            self.logger.info(f"Placing BUY order for ${amount:.2f} of {SYMBOL}")
            self.logger.info("-------------------------------------")
            
            try:
                order_id = self.client.place_buy_order(account_id, contract_id, amount)
                
                trade = Trade(
                    account_id=account_id,
                    action="Buy",
                    symbol=SYMBOL,
                    dollar_amount=amount,
                    shares=quantity,
                    order_id=order_id
                )
                self.trade_logger.log_trade(trade)
                
            except OrderRejectionError as e:
                raise  # Re-raise to be caught by the main exception handler
        else:
            self.logger.warning("Insufficient cash for purchase.")
    
    def _handle_bearish_or_neutral_signal(self, account_id: str, contract_id: int, price: float, current_position: float) -> None:
        """Handle bearish or neutral signal by selling the symbol."""

        if current_position > 0:
            quantity = current_position
            amount = quantity * price
            self.logger.info(f"Placing SELL order for {quantity} shares of {SYMBOL}")
            self.logger.info("-------------------------------------")

            try:
                order_id = self.client.place_sell_order(account_id, contract_id, quantity)
                
                trade = Trade(
                    account_id=account_id,
                    action="Sell",
                    symbol=SYMBOL,
                    dollar_amount=amount,
                    shares=quantity,
                    order_id=order_id
                )
                self.trade_logger.log_trade(trade)
                
            except OrderRejectionError as e:
                raise  # Re-raise to be caught by the main exception handler

        else:
            self.logger.info(f"No {SYMBOL} position to sell.")

    def _get_ibkr_commission(self, quantity: float, price: float, commission_type: str) -> float:
        """Get IBKR Pro commission estimate."""

        trade_value = quantity * price

        if commission_type.upper() == "TIERED":
            commission = quantity * TIERED_RATE_PER_SHARE
            commission = max(commission, TIERED_MIN_COMMISSION)
            commission = min(commission, trade_value * TIERED_MAX_COMMISSION_PCT)

        elif commission_type.upper() == "FIXED":
            commission = quantity * FIXED_RATE_PER_SHARE
            commission = max(commission, FIXED_MIN_COMMISSION)

        else:
            raise ValueError("Invalid commission_type. Must be 'TIERED' or 'FIXED'.")

        return round(commission, 2)
