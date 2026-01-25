"""Main trading execution logic."""

from algo_trader.clients import IBKRClient
from algo_trader.core.strategy import TradingStrategy
from algo_trader.logging import get_logger, TradeLogger
from algo_trader.models import Trade, Signal, Severity
from algo_trader.notifications import NotificationService
from algo_trader.utils.config import SYMBOL, COMMISSION_TYPE


class Trader:
    """Main trader class that orchestrates trading operations."""
    
    def __init__(self):
        self.client = IBKRClient()
        self.strategy = TradingStrategy()
        self.trade_logger = TradeLogger()
        self.logger = get_logger()
        self.notifications = NotificationService()

    def execute_trade(self) -> None:
        """Execute the main trading logic."""
        try:
            # Initialize client (auth check + order reply suppression)
            if not self.client.initialize():
                raise Exception("Failed to initialize IBKR client")
                
            account_id = self.client.get_account_id()
            contract_id = self.client.get_contract_id(SYMBOL)
            
            # Initialize CloudWatch with account-specific log group
            self.logger.initialize_cloudwatch(account_id)
            self.logger.info("----------------BEGIN----------------")
            
            signal = self.strategy.get_signal()
            self.logger.info(f"Market Signal: {signal.name}")
            self.notifications.send_notification(account_id, Severity.INFO, f"Market Signal - {signal.name}")
            
            price = self.client.get_price(contract_id)
            current_position = self.client.get_position(account_id, contract_id)
            
            self.logger.info(f"{SYMBOL} Price: ${price:.2f}")
            self.logger.info(f"Current Position: {current_position} shares")
            
            if signal == Signal.BULLISH:
                self._handle_bullish_signal(account_id, contract_id, price)
            elif signal == Signal.BEARISH or signal == Signal.NEUTRAL:
                self._handle_bearish_or_neutral_signal(account_id, contract_id, price, current_position)

        except Exception as e:
            self.logger.error(f"Trade execution failed: {e}")
            raise
        finally:
            self.logger.info("-----------------END-----------------")
    
    def _handle_bullish_signal(self, account_id: str, contract_id: int, price: float) -> None:
        """Handle bullish signal by buying the symbol."""
        available_cash = self.client.get_available_cash(account_id)
        self.logger.info(f"Available Cash: ${available_cash:.2f}")
        
        if available_cash > 5:
            quantity = available_cash / price
            commission = self._get_ibkr_commission(quantity, price, COMMISSION_TYPE)
            amount = available_cash - commission - 1

            self.logger.info(f"Commission Estimate: ${commission:.2f}")
            self.logger.info(f"Placing BUY order for ${amount:.2f} of {SYMBOL}")
            
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
        else:
            self.logger.warning("Insufficient cash for purchase.")
    
    def _handle_bearish_or_neutral_signal(self, account_id: str, contract_id: int, price: float, current_position: float) -> None:
        """Handle bearish or neutral signal by selling the symbol."""
        if current_position > 0:
            quantity = int(current_position)
            amount = quantity * price
            self.logger.info(f"Placing SELL order for {quantity} shares of {SYMBOL}")

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
        else:
            self.logger.info(f"No {SYMBOL} position to sell.")

    def _get_ibkr_commission(self, quantity: float, price: float, commission_type: str) -> float:
        """Get IBKR Pro commission estimate."""

        trade_value = quantity * price

        if commission_type.upper() == "TIERED":
            RATE_PER_SHARE = 0.0035     # $0.0035 per share
            MIN_COMMISSION = 0.35       # Minimum per order
            MAX_COMMISSION_PCT = 0.01   # Max 1% of trade value

            commission = quantity * RATE_PER_SHARE
            commission = max(commission, MIN_COMMISSION)
            commission = min(commission, trade_value * MAX_COMMISSION_PCT)

        elif commission_type.upper() == "FIXED":
            RATE_PER_SHARE = 0.005      # $0.005 per share
            MIN_COMMISSION = 1.00       # Minimum per order

            commission = quantity * RATE_PER_SHARE
            commission = max(commission, MIN_COMMISSION)

        else:
            raise ValueError("Invalid commission_type. Must be 'TIERED' or 'FIXED'.")

        return round(commission, 2)
