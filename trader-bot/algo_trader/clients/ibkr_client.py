"""IBKR Web API client for trading operations."""

import urllib3
from typing import Optional
import requests
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
from datetime import datetime

from algo_trader.logging import get_logger
from algo_trader.utils.config import BASE_URL, VERIFY_SSL, MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF
from algo_trader.utils.decorators import retry


class OrderRejectionError(Exception):
    """Exception raised when an order is rejected by IBKR."""
    
    def __init__(self, message: str, rejection_details: dict = None):
        super().__init__(message)
        self.rejection_details = rejection_details or {}


class IBKRClient:
    """Interactive Brokers Web API client."""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.verify = VERIFY_SSL
        self._account_id: Optional[str] = None
        self.logger = get_logger()
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        # Message IDs to suppress for order reply messages
        self.suppress_message_ids = [
            "o163",   # Order exceeds the price percentage limit
            "o354",   # Submitting an order without market data
            "o382",   # Value exceeds the tick size limit
            "o383",   # Order size exceeds the size limit
            "o403",   # Order will fill immediately
            "o451",   # Order value exceeds the value limit
            "o10151", # Market order risks
            "o10164", # Traders are responsible for understanding cash quantity details
            "o10223"  # Orders that express size using a monetary value are provided on a non-guaranteed basis
        ]

    def initialize(self):
        """Initialize the client by checking auth and suppressing order reply messages."""
        try:
            self._check_auth()
            self._suppress_order_reply_messages()
            self.logger.info("IBKR client initialized successfully")
          
        except Exception as e:
            self.logger.error(f"Failed to initialize IBKR client: {e}")
            raise  # Re-raise the original exception

    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF)
    def _check_auth(self):
        """Check if authenticated with IBKR Web API."""
        response = self.session.get(f"{BASE_URL}/iserver/auth/status")
        response.raise_for_status()
        
        is_authenticated = response.json().get("authenticated", False)
        if not is_authenticated:
            raise Exception("Not authenticated with IBKR Web API")
        
        self.logger.info("Authenticated with IBKR Web API")

    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF)
    def _suppress_order_reply_messages(self):
        """Suppress specified order reply messages for the current session."""
        response = self.session.post(f"{BASE_URL}/iserver/questions/suppress",
                                     json={"messageIds": self.suppress_message_ids})
        response.raise_for_status()

        status = response.json().get("status")
        if status != 'submitted':
            raise Exception(f"Failed to suppress order reply messages: unexpected status '{status}'")

        self.logger.info(f"Successfully suppressed {len(self.suppress_message_ids)} order reply message types")

    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF)
    def get_account_id(self) -> str:
        """Get the primary account ID."""
        if self._account_id:
            return self._account_id
            
        response = self.session.get(f"{BASE_URL}/iserver/accounts")
        response.raise_for_status()
        
        data = response.json()
        accounts = data.get("accounts", [])
        if not accounts:
            raise Exception("No accounts found in response")
        
        self._account_id = accounts[0]
        if self._account_id is not None and self._account_id != "":
            return self._account_id

        raise Exception("Account ID is empty or None")

    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF)
    def get_available_cash(self, account_id: str) -> float:
        """Get available cash for trading."""
        response = self.session.get(f"{BASE_URL}/iserver/account/{account_id}/summary")
        response.raise_for_status()
        
        data = response.json()
        available_cash = data.get("availableFunds")
        if available_cash is not None:
            return float(available_cash)

        raise Exception(f"Failed to get available cash - 'availableFunds' not found in response")

    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF)
    def get_account_balance(self, account_id: str) -> float:
        """Get account balance (equity with loan value)."""
        response = self.session.get(f"{BASE_URL}/iserver/account/{account_id}/summary")
        response.raise_for_status()
        
        data = response.json()
        net_liquidation_value = data.get("netLiquidationValue")
        if net_liquidation_value is not None:
            return float(net_liquidation_value)

        raise Exception(f"Failed to get account balance - 'netLiquidationValue' not found in response")

    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF)
    def get_contract_id(self, symbol: str, sec_type="STK") -> int:
        """Get contract id for a symbol."""
        response = self.session.get(f"{BASE_URL}/iserver/secdef/search",
                                    params={"symbol": symbol, "secType": sec_type})
        response.raise_for_status()
        
        data = response.json()
        if data and isinstance(data, list) and len(data) > 0:
            first_result = data[0]
            conid = first_result.get("conid")
            if conid is not None:
                return int(conid)

        raise Exception(f"Contract ID not found for symbol {symbol}")

    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF)
    def get_price(self, conid: int) -> float:
        """Get price for a contract."""
        response = self.session.get(f"{BASE_URL}/iserver/marketdata/history",
                                    params={"conid": conid, "period": "5d", "bar": "1d", "outsideRth": "true"})
        response.raise_for_status()
        data = response.json()
        bars = data.get("data", [])
        if bars and len(bars) > 0:
            last_bar = bars[-1]
            close_price = last_bar.get("c")
            if close_price is not None:
                return float(close_price)

        raise Exception(f"Price not found for contract ID {conid}")

    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF)
    def get_position(self, account_id: str, conid: int) -> float:
        """Get current position for a given contract ID."""
        response = self.session.get(f"{BASE_URL}/portfolio/{account_id}/positions/0")
        response.raise_for_status()
        
        positions = response.json()
        if not isinstance(positions, list):
            raise Exception(f"Unexpected response format for positions")
        
        for position in positions:
            if position.get("conid") == conid:
                position_value = position.get("position")
                if position_value is not None:
                    return float(position_value)
        
        # Return 0.0 if position not found (no position in this contract)
        return 0.0

    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF, no_retry_exceptions=[OrderRejectionError])
    def place_sell_order(self, account_id: str, conid: int, quantity: float) -> Optional[str]:
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

    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF, no_retry_exceptions=[OrderRejectionError])
    def place_buy_order(self, account_id: str, conid: int, cash_quantity: float) -> Optional[str]:
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

    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF, no_retry_exceptions=[OrderRejectionError])
    def _place_market_order(self, account_id: str, payload: dict) -> Optional[str]:
        """Place a market order with the given payload. Returns order ID if available."""

        response = self.session.post(
            f"{BASE_URL}/iserver/account/{account_id}/orders",
            json=payload
        )
        response.raise_for_status()
        
        result = response.json()
        self.logger.info(f"Order response: {result}")
        
        # Check for order rejection
        if isinstance(result, dict) and "error" in result:
            error_message = result["error"]
            rejection_details = result.get("cqe", {})
            
            # Extract rejection reason from cqe if available
            if rejection_details and "post_payload" in rejection_details:
                rejections = rejection_details["post_payload"].get("rejections", [])

                if rejections:
                    # Use the first rejection reason as the primary error message
                    primary_rejection = rejections[0]
                    raise OrderRejectionError(primary_rejection, rejection_details)
            
            # Fallback to the main error message
            raise OrderRejectionError(error_message, rejection_details)
        
        order_id = None
        
        if isinstance(result, list) and len(result) > 0:

            first_result = result[0]

            # Check for order_id in the initial response
            order_id = first_result.get("order_id")
            if order_id:
                self.logger.info(f"Order ID from initial response: {order_id}")
            
            # Handle confirmation if needed
            confirm_id = first_result.get("id")
            if confirm_id:
                confirmation_order_id = self._confirm_order(confirm_id)

                # Use confirmation order_id if we didn't get one from initial response
                if order_id is None and confirmation_order_id is not None:
                    order_id = confirmation_order_id
        
        return order_id

    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF, no_retry_exceptions=[OrderRejectionError])
    def _confirm_order(self, confirm_id: str) -> Optional[str]:
        """Confirm an order that requires confirmation. Returns order_id if available."""

        response = self.session.post(
            f"{BASE_URL}/iserver/reply/{confirm_id}",
            json={"confirmed": True}
        )
        response.raise_for_status()
        
        result = response.json()
        self.logger.info(f"Order confirmation response: {result}")
        
        # Check for order rejection in confirmation response
        if isinstance(result, dict) and "error" in result:
            error_message = result["error"]
            rejection_details = result.get("cqe", {})
            
            # Extract rejection reason from cqe if available
            if rejection_details and "post_payload" in rejection_details:
                rejections = rejection_details["post_payload"].get("rejections", [])

                if rejections:
                    # Use the first rejection reason as the primary error message
                    primary_rejection = rejections[0]
                    raise OrderRejectionError(primary_rejection, rejection_details)
            
            # Fallback to the main error message
            raise OrderRejectionError(error_message, rejection_details)
        
        # Extract order_id from confirmation response
        order_id = None
        if isinstance(result, list) and len(result) > 0:
            order_id = result[0].get("order_id")
            if order_id:
                self.logger.info(f"Order ID from confirmation: {order_id}")
        elif isinstance(result, dict):
            order_id = result.get("order_id")
            if order_id:
                self.logger.info(f"Order ID from confirmation: {order_id}")
        
        self.logger.info("Order confirmed")
        return order_id

    def get_performance(self, account_id: str, notifications_service) -> None:
        """Get account performance for the last 1 year, plot it, and send via Telegram."""
        try:
            # Get performance data for last 1 year
            response = self.session.post(
                f"{BASE_URL}/pa/performance",
                json={
                    "acctIds": [account_id],
                    "period": "1Y",
                    "freq": "D"
                }
            )
            response.raise_for_status()
            
            data = response.json()
            performance_data = data.get("data", {})
            returns = performance_data.get("returns", [])
            
            if not returns:
                self.logger.warning("No performance data available")
                return
            
            # Parse dates and values
            dates = []
            values = []
            
            for item in returns:
                date_str = item.get("date")
                value = item.get("value")
                
                if date_str and value is not None:
                    try:
                        date_obj = datetime.strptime(date_str, "%Y%m%d")
                        dates.append(date_obj)
                        values.append(float(value))
                    except ValueError as e:
                        self.logger.warning(f"Failed to parse date {date_str}: {e}")
                        continue
            
            if not dates or not values:
                self.logger.warning("No valid performance data to plot")
                return
            
            # Create and save the plot
            plt.figure(figsize=(16, 9))
            plt.plot(dates, values, linewidth=2, color='#1f77b4')
            plt.title('Account Performance - Last 1 Year', fontsize=16, fontweight='bold')
            plt.xlabel('Date', fontsize=12)
            plt.ylabel('Return (%)', fontsize=12)
            plt.grid(True, alpha=0.3)
            plt.tight_layout()
            plt.savefig('performance.png', dpi=300, bbox_inches='tight')
            plt.close()
            
            # Send via Telegram
            caption = f"📈 Account Performance - Last 1 Year\n👤 Account: {account_id}"
            notifications_service.send_telegram_image(image_path, caption)
            
        except Exception as e:
            self.logger.error(f"Failed to get performance data: {e}")
