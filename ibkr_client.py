"""Interactive Brokers Web API client using ibind."""

import yfinance as yf
from ibind import IbkrWsKey, IbkrClient
from typing import Optional

from config import BASE_URL, VERIFY_SSL
from utils import retry


class IBKRClient:
    """Simplified client for interacting with IBKR Web API using ibind."""
    
    def __init__(self):
        # Initialize ibind client
        self.client = IbkrClient(
            base_url=BASE_URL,
            verify=VERIFY_SSL
        )
        self._account_id: Optional[str] = None
    
    @retry()
    def check_auth(self) -> None:
        """Check if authenticated with IBKR Web API."""
        auth_status = self.client.auth_status()
        if not auth_status.get("authenticated", False):
            raise Exception("Not authenticated with IBKR Web API")
        print("Authenticated with IBKR Web API")
    
    @retry()
    def get_account_id(self) -> str:
        """Get the first available account ID."""
        if self._account_id is None:
            accounts = self.client.accounts()
            self._account_id = accounts["accounts"][0]
        return self._account_id
    
    @retry()
    def get_available_cash(self, account_id: str) -> float:
        """Get available cash for the account."""
        summary = self.client.account_summary(account_id)
        print(f"Account summary received")
        return float(summary["availableFunds"])
    
    @retry()
    def get_position(self, account_id: str, conid: int) -> float:
        """Get position size for a specific contract."""
        positions = self.client.portfolio_positions(account_id, page_id=0)
        
        for position in positions:
            if position["conid"] == conid:
                return float(position["position"])
        return 0.0
    
    @retry()
    def get_price(self, symbol: str) -> float:
        """Get the latest price for a symbol using Yahoo Finance."""
        ticker = yf.Ticker(symbol)
        history = ticker.history(period="1d")
        return float(history["Close"].iloc[-1])
    
    @retry()
    def place_market_order(self, account_id: str, conid: int, side: str, quantity: int) -> None:
        """Place a market order."""
        order = {
            "conid": conid,
            "secType": "STK",
            "orderType": "MKT",
            "side": side,
            "quantity": quantity,
            "tif": "DAY",
            "exchange": "SMART",
            "currency": "USD"
        }
        
        result = self.client.place_orders(account_id, [order])
        print(f"Order response: {result}")
        
        # Handle order confirmations using ibind's built-in methods
        if isinstance(result, list) and "id" in result[0]:
            confirm_id = result[0]["id"]
            self._confirm_order(confirm_id)
    
    @retry()
    def lookup_contract(self, symbol: str) -> int:
        """Look up contract ID (conid) for a given symbol."""
        contracts = self.client.contract_search(symbol)
        
        # Look for exact symbol match for stocks
        for contract in contracts:
            if (contract.get("symbol") == symbol and 
                contract.get("secType") == "STK" and
                contract.get("exchange") == "SMART"):
                conid = contract["conid"]
                print(f"Found conid {conid} for {symbol}")
                return conid
        
        # If no exact match, return the first stock result
        for contract in contracts:
            if contract.get("secType") == "STK":
                conid = contract["conid"]
                print(f"Found conid {conid} for {symbol} (first stock match)")
                return conid
        
        raise Exception(f"No contract found for symbol {symbol}")
    
    @retry()
    def _confirm_order(self, confirm_id: str) -> None:
        """Confirm an order that requires confirmation."""
        self.client.reply_to_question(confirm_id, confirmed=True)
        print("Order confirmed")