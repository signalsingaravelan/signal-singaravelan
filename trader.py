"""Main trading execution logic."""

from config import SYMBOL, TQQQ_CONTRACT_ID, MAX_PER_ORDER
from ibkr_client import IBKRClient, MarketDataProvider
from strategy import TradingStrategy
from utils import Signal


class Trader:
    """Main trader class that orchestrates trading operations."""
    
    def __init__(self):
        self.client = IBKRClient()
        self.market_data = MarketDataProvider()
        self.strategy = TradingStrategy()
    
    def execute_trade(self) -> None:
        """Execute the main trading logic."""
        try:
            # Authenticate and get account info
            self.client.check_auth()
            account_id = self.client.get_account_id()
            
            # Get market signal and current market data
            signal = self.strategy.get_signal()
            print(f"Market signal: {signal.name}")
            
            price = self.market_data.get_price(SYMBOL)
            current_position = self.client.get_position(account_id, int(TQQQ_CONTRACT_ID))
            
            print(f"{SYMBOL} Price: ${price:.2f}")
            print(f"Current Position: {current_position} shares")
            
            # Execute trading logic based on signal
            if signal == Signal.BULLISH:
                self._handle_bullish_signal(account_id, price)
            elif signal == Signal.BEARISH:
                self._handle_bearish_signal(account_id, current_position)
            else:
                print("Neutral signal - no action taken")
                
        except Exception as e:
            print(f"Trade execution failed: {e}")
            raise
    
    def _handle_bullish_signal(self, account_id: str, price: float) -> None:
        """Handle bullish signal by buying the symbol."""
        available_cash = self.client.get_available_cash(account_id)
        print(f"Available cash: ${available_cash:.2f}")
        
        if available_cash > 0:
            cash_amount = min(available_cash, MAX_PER_ORDER)
            print(f"Placing BUY order for ${cash_amount:.2f} of {SYMBOL}")
            self.client.place_buy_order(account_id, TQQQ_CONTRACT_ID, cash_amount)
        else:
            print("Insufficient cash for purchase")
    
    def _handle_bearish_signal(self, account_id: str, current_position: float) -> None:
        """Handle bearish signal by selling the symbol."""
        if current_position > 0:
            quantity = int(current_position)
            print(f"Placing SELL order for {quantity} shares of {SYMBOL}")
            self.client.place_sell_order(account_id, TQQQ_CONTRACT_ID, quantity)
        else:
            print(f"No {SYMBOL} position to sell")