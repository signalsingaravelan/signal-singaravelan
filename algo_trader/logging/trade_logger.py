"""Trade logging functionality for Excel reporting."""

import os
from datetime import datetime
from typing import Optional

import pandas as pd

from algo_trader.logging.cloudwatch_logger import get_logger
from algo_trader.notifications import NotificationService

TRADE_HISTORY_FILENAME_TEMPLATE = "{account_id}-order-history.xlsx"


class TradeLogger:
    """Handles logging of trade information to Excel files and notifications."""
    
    def __init__(self, output_dir: str = "../trade-output/"):
        self.output_dir = output_dir
        self.logger = get_logger()
        self.notification_service = NotificationService()
        self._ensure_output_directory()
    
    def _ensure_output_directory(self) -> None:
        """Ensure the output directory exists."""
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
    
    def _generate_order_id(self) -> str:
        """Generate a simple order ID based on timestamp."""
        return f"ORD_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    def log_trade(self, account_id: str, action: str, symbol: str, 
                  dollar_amount: float, shares: float, order_id: Optional[str] = None) -> str:
        """
        Log trade information to Excel file.
        
        Args:
            account_id: The trading account ID
            action: Buy or Sell
            symbol: Trading symbol
            dollar_amount: Dollar value of the trade
            shares: Number of shares (fractional supported)
            order_id: Optional order ID, will generate if not provided
            
        Returns:
            The order ID used for logging
        """
        if order_id is None:
            order_id = self._generate_order_id()
            
        try:
            filename = TRADE_HISTORY_FILENAME_TEMPLATE.format(account_id=account_id)
            filepath = os.path.join(self.output_dir, filename)
            
            trade_record = {
                'Date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'OrderId': order_id,
                'Action': action,
                'Symbol': symbol,
                'Dollar Amount': dollar_amount,
                'Shares': round(shares, 2)
            }
            
            if os.path.exists(filepath):
                try:
                    existing_df = pd.read_excel(filepath)
                    new_df = pd.concat([existing_df, pd.DataFrame([trade_record])], ignore_index=True)
                except Exception as e:
                    self.logger.warning(f"Could not read existing Excel file: {e}")
                    new_df = pd.DataFrame([trade_record])
            else:
                new_df = pd.DataFrame([trade_record])
            
            new_df.to_excel(filepath, index=False, engine='openpyxl')
            self.logger.info(f"Trade logged to {filepath}")
            
            # Send notifications
            self.notification_service.send_trade_notification(
                account_id, action, symbol, dollar_amount, shares, order_id
            )
            
        except Exception as e:
            self.logger.error(f"Error logging trade to Excel: {e}")
        
        return order_id
    
    def get_trade_history(self, account_id: str) -> Optional[pd.DataFrame]:
        """
        Retrieve trade history for a given account.
        
        Args:
            account_id: The trading account ID
            
        Returns:
            DataFrame with trade history or None if file doesn't exist
        """
        try:
            filename = TRADE_HISTORY_FILENAME_TEMPLATE.format(account_id=account_id)
            filepath = os.path.join(self.output_dir, filename)
            
            if os.path.exists(filepath):
                return pd.read_excel(filepath)
            else:
                self.logger.info(f"No trade history file found for account {account_id}")
                return None
                
        except Exception as e:
            self.logger.error(f"Error reading trade history: {e}")
            return None
    
    def test_notifications(self) -> None:
        """Send test notifications to verify configuration."""
        self.notification_service.send_test_notification()
