"""Main trading bot implementation."""

from config import DEFAULT_SYMBOL, MAX_POSITION_SIZE
from ibkr_client import IBKRClient
from strategy import TradingStrategy
from utils import Signal


class TradingBot:
    """Main trading bot that orchestrates the trading logic."""
    
    def __init__(self, symbol: str = DEFAULT_SYMBOL):
        self.ibkr_client = IBKRClient()
        self.strategy = TradingStrategy()
        self.symbol = symbol
    
    def execute_trade(self) -> None:
        """Execute the main trading logic."""
        try:
            # Authenticate and get account info
            self.ibkr_client.check_auth()
            account_id = self.ibkr_client.get_account_id()
            
            # Look up contract ID for the symbol (fresh lookup every time)
            conid = self.ibkr_client.lookup_contract(self.symbol)
            
            # Get market signal and data
            signal = self.strategy.get_signal()
            print(f"Trading signal: {signal.name}")
            
            price = self.ibkr_client.get_price(self.symbol)
            position = self.ibkr_client.get_position(account_id, conid)
            
            # Execute trading logic based on signal
            if signal == Signal.BULLISH:
                self._handle_bullish_signal(account_id, conid, price)
            elif signal == Signal.BEARISH:
                self._handle_bearish_signal(account_id, conid, position)
            else:
                print("Neutral signal – no action taken")
                
        except Exception as e:
            print(f"Trading execution failed: {e}")
            raise
    
    def _handle_bullish_signal(self, account_id: str, conid: int, price: float) -> None:
        """Handle bullish signal by buying the symbol."""
        cash = self.ibkr_client.get_available_cash(account_id)
        max_shares = int(cash // price)
        quantity = min(int(MAX_POSITION_SIZE), max_shares)
        
        print(f"Available cash: ${cash:.2f}, {self.symbol} price: ${price:.2f}, Max quantity: {quantity}")
        
        if quantity > 0:
            self.ibkr_client.place_market_order(account_id, conid, "BUY", quantity)
            print(f"Placed BUY order for {quantity} shares of {self.symbol}")
        else:
            print("Insufficient cash to place buy order")
    
    def _handle_bearish_signal(self, account_id: str, conid: int, position: float) -> None:
        """Handle bearish signal by selling the position."""
        if position > 0:
            quantity = int(position)
            self.ibkr_client.place_market_order(account_id, conid, "SELL", quantity)
            print(f"Placed SELL order for {quantity} shares of {self.symbol}")
        else:
            print(f"No {self.symbol} position to sell")