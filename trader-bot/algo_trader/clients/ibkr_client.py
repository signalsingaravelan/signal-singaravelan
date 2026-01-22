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
    def place_sell_order(self, account_id: str, conid: int, quantity: int) -> Optional[str]:
        """Place a sell market order. Returns order ID if available."""
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
        return self._place_market_order(account_id, payload)

    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF)
    def place_buy_order(self, account_id: str, conid: int, cash_quantity: int) -> Optional[str]:
        """Place a buy market order using cash quantity. Returns order ID if available."""
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
        return self._place_market_order(account_id, payload)

    def _place_market_order(self, account_id: str, payload: dict) -> Optional[str]:
        """Place market order and handle confirmation flow. Returns order ID."""
        response = self.session.post(
            f"{BASE_URL}/iserver/account/{account_id}/orders",
            json=payload
        )
        response.raise_for_status()
        result = response.json()
        self.logger.info(f"Order response: {result}")
        
        if not isinstance(result, list) or not result:
            raise Exception("Order failed - no order ID received")
        
        order_data = result[0]
        
        # Return order ID if immediately available
        if "order_id" in order_data:
            order_id = order_data["order_id"]
        elif "id" in order_data:
            # Handle confirmation flow if required
            order_id = self._confirm_order(order_data["id"])
        else:
            order_id = None

        if order_id is None:
            raise Exception("Order failed - no order ID received")

        self.logger.info(f"Order confirmed with ID: {order_id}")

        return order_id
    
    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF)
    def _confirm_order(self, confirm_id: str, max_attempts: int = 5) -> Optional[str]:
        """
        Confirm order through multiple rounds if needed.
        
        IBKR Message Codes (auto-confirmed):
        - o383: Size Limit Warning
                "The following order size exceeds the Size Limit of 500."
                Triggered when order quantity exceeds configured size limit.
        
        - o451: Total Value Limit Warning
                "The following order cash quantity exceeds the Total Value Limit of 100,000 USD."
                Triggered when order value exceeds configured dollar limit.
        
        - o354: No Market Data Warning
                "You are submitting an order without market data."
                Triggered when placing orders without active market data subscription.
        
        - o10164: Cash Quantity Responsibility Notice
                "Traders are responsible for understanding cash quantity details."
                Informational notice about cash quantity order mechanics.
        
        - o10223: Cash Quantity Order Confirmation
                "Orders that express size using a monetary value (cash quantity) are provided on a non-guaranteed basis."
                Explains that cash quantity orders are simulated and use Cash Quantity Estimate Factor.
        
        Returns:
            order_id on success, None on failure
        """
        ALLOWED_MESSAGE_IDS = {"o383", "o451", "o354", "o10164", "o10223"}
        
        for attempt in range(1, max_attempts + 1):
            self.logger.info(f"Confirmation attempt {attempt}/{max_attempts} for ID: {confirm_id}")
            
            result = self._send_confirmation(confirm_id)
            order_id = self._get_field(result, "order_id")
            
            if order_id:
                self.logger.info(f"Order confirmed successfully with ID: {order_id}")
                return order_id
            
            # Check for next confirmation round
            next_id = self._get_field(result, "id")
            if not next_id:
                self.logger.warning("No order_id or confirmation_id in response")
                break
            
            message_ids = self._get_field(result, "messageIds") or []
            if not any(msg_id in ALLOWED_MESSAGE_IDS for msg_id in message_ids):
                self.logger.warning(f"Unsupported message IDs: {message_ids}")
                break
            
            self.logger.info(f"Auto-confirming IBKR warning: {message_ids}")
            confirm_id = next_id
        
        self.logger.error(f"Confirmation failed after {attempt} attempts")
        return None
    
    def _send_confirmation(self, confirm_id: str) -> dict:
        """Send confirmation request and return response."""
        response = self.session.post(
            f"{BASE_URL}/iserver/reply/{confirm_id}",
            json={"confirmed": True}
        )
        response.raise_for_status()
        result = response.json()
        self.logger.info(f"Confirmation response: {result}")
        return result
    
    def _get_field(self, result, field: str):
        """Extract field from response (handles both list and dict formats)."""
        if isinstance(result, list) and result:
            return result[0].get(field)
        if isinstance(result, dict):
            return result.get(field)
        return None

