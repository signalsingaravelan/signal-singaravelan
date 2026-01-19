"""IBKR Web API client for trading operations."""

import urllib3
from typing import Optional
import requests

from algo_trader.logging import get_logger
from algo_trader.utils.config import (
    BASE_URL, VERIFY_SSL, MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF
)
from algo_trader.utils.decorators import retry


class IBKRClient:
    """Interactive Brokers Web API client."""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.verify = VERIFY_SSL
        self._account_id: Optional[str] = None
        self.logger = get_logger()
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF)
    def check_auth(self) -> bool:
        """Check if authenticated with IBKR Web API."""
        response = self.session.get(f"{BASE_URL}/iserver/auth/status")
        response.raise_for_status()
        
        is_authenticated = response.json().get("authenticated", False)
        if not is_authenticated:
            raise Exception("Not authenticated with IBKR Web API")
        
        self.logger.info("Authenticated with IBKR Web API")
        return True
    
    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF)
    def get_account_id(self) -> str:
        """Get the primary account ID."""
        if self._account_id:
            return self._account_id
            
        response = self.session.get(f"{BASE_URL}/iserver/accounts")
        response.raise_for_status()
        
        self._account_id = response.json()["accounts"][0]
        return self._account_id
    
    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF)
    def get_available_cash(self, account_id: str) -> float:
        """Get available cash for trading."""
        response = self.session.get(f"{BASE_URL}/iserver/account/{account_id}/summary")
        response.raise_for_status()
        
        data = response.json()
        return float(data["availableFunds"])

    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF)
    def get_contract_id(self, symbol: str, sec_type="STK") -> int:
        """Get contract id for a symbol."""
        response = self.session.get(f"{BASE_URL}/iserver/secdef/search",
                                    params={"symbol": symbol, "secType": sec_type})
        response.raise_for_status()
        
        data = response.json()
        if data and isinstance(data, list):
            return int(data[0]["conid"])

        raise Exception(f"Conid not found for symbol {symbol}")

    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF)
    def get_price(self, conid: int) -> float:
        """Get price for a contract."""
        response = self.session.get(f"{BASE_URL}/iserver/marketdata/snapshot",
                                    params={"conids": conid, "fields": "31,84,86"})
        response.raise_for_status()

        data = response.json()
        if not data or not isinstance(data, list):
            raise Exception("Invalid market data response.")
        snapshot = data[0]

        # Try prices in order of preference
        # 31 = last price
        # 84 = mark price
        # 86 = close price
        for field in ("31", "84", "86"):
            price = snapshot.get(field)
            if price is not None:
                try:
                    return float(price)
                except ValueError:
                    continue

        raise Exception(f"Price not found for conid {conid}.")

    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF)
    def get_position(self, account_id: str, conid: int) -> float:
        """Get current position for a given contract ID."""
        response = self.session.get(f"{BASE_URL}/portfolio/{account_id}/positions/0")
        response.raise_for_status()
        
        for position in response.json():
            if position["conid"] == conid:
                return float(position["position"])
        return 0.0
    
    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF)
    def place_sell_order(self, account_id: str, conid: int, quantity: int) -> None:
        """Place a sell market order."""
        payload = {
            "orders": [{
                "conid": conid,
                "secType": "STK",
                "orderType": "MKT",
                "side": "SELL",
                "quantity": quantity,
                "tif": "DAY",
                "exchange": "SMART",
                "currency": "USD"
            }]
        }
        self._place_market_order(account_id, payload)

    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF)
    def place_buy_order(self, account_id: str, conid: int, cash_quantity: int) -> None:
        """Place a buy market order using cash quantity."""
        payload = {
            "orders": [{
                "conid": conid,
                "secType": "STK",
                "orderType": "MKT",
                "side": "BUY",
                "cashQty": cash_quantity,
                "tif": "DAY",
                "exchange": "SMART",
                "currency": "USD"
            }]
        }
        self._place_market_order(account_id, payload)

    def _place_market_order(self, account_id: str, payload: dict) -> None:
        """Place a market order with the given payload."""
        response = self.session.post(
            f"{BASE_URL}/iserver/account/{account_id}/orders",
            json=payload
        )
        response.raise_for_status()
        
        result = response.json()
        self.logger.info(f"Order response: {result}")
        
        if isinstance(result, list) and "id" in result[0]:
            self._confirm_order(result[0]["id"])
    
    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF)
    def _confirm_order(self, confirm_id: str) -> None:
        """Confirm an order that requires confirmation."""
        response = self.session.post(
            f"{BASE_URL}/iserver/reply/{confirm_id}",
            json={"confirmed": True}
        )
        response.raise_for_status()
        self.logger.info("Order confirmed")

