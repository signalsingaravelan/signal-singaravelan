"""Notification service for trade alerts via email and Telegram."""

import os
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional

import boto3
import requests
from botocore.exceptions import ClientError

from algo_trader.models import Trade, Severity
from algo_trader.logging import get_logger
from algo_trader.utils.config import (
    EMAIL_FROM, EMAIL_TO, EMAIL_REGION,
    TELEGRAM_CHAT_ID,
)
from algo_trader.utils.secrets import get_secret_value

class NotificationService:
    """Handles sending trade notifications via email and Telegram."""
    
    def __init__(self):
        self.logger = get_logger()
        self.ses_client = self._setup_ses_client()
        self.telegram_token = self._get_telegram_token()
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID)
    
    def _setup_ses_client(self) -> Optional[boto3.client]:
        """Initialize AWS SES client."""
        try:
            return boto3.client("ses", region_name=EMAIL_REGION)
        except Exception as e:
            self.logger.warning(f"SES client initialization failed: {e}")
            return None
    
    def _get_telegram_token(self) -> Optional[str]:
        """Read Telegram bot token from the shared Secrets Manager cache."""
        try:
            telegram_token = get_secret_value("TELEGRAM_BOT_TOKEN")
            
            if telegram_token:
                self.logger.info("Successfully retrieved Telegram bot token from Secrets Manager")
                return telegram_token
            else:
                self.logger.error("TELEGRAM_BOT_TOKEN key not found in secret")
                return None
                
        except Exception as e:
            self.logger.error(f"Unexpected error retrieving Telegram token: {e}")
            return None
    
    def send_notification(self, account_id: str, severity: Severity, message: str) -> None:
        """Send notification via email and Telegram."""
        timestamp = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S")
        message = f"""
📅 Time: {timestamp}
👤 Account: {account_id}
🏷️ Severity: {severity.name}
📊 Message: {message}"""

        # Send email notification
        self._send_email(f"Sig-Sriram > Account: {account_id} > {severity}", message)
        
        # Send Telegram notification
        self._send_telegram(message)

    def send_trade_notification(self, trade: Trade) -> None:
        """Send trade notification via email and Telegram."""
        message = self._format_trade_message(trade)
        
        # Send email notification
        self._send_email(f"Trade Executed: {trade.action} {trade.symbol}", message)
        
        # Send Telegram notification
        self._send_telegram(message)
    
    def _format_trade_message(self, trade: Trade) -> str:
        """Format trade information into a readable message."""
        return f"""🤖 Trade Executed

📅 Time: {trade.formatted_timestamp}
👤 Account: {trade.account_id}
📊 Action: {trade.action}
🏷️ Symbol: {trade.symbol}
💰 Amount: ${trade.dollar_amount:.2f}
📈 Shares: {trade.shares:.2f}
🆔 Order ID: {trade.order_id or 'N/A'}"""
    
    def _send_email(self, subject: str, message: str) -> None:
        """Send email notification via AWS SES."""
        if not self.ses_client or not EMAIL_TO:
            self.logger.debug("Email notification skipped - SES not configured")
            return
        
        try:
            response = self.ses_client.send_email(
                Source=EMAIL_FROM,
                Destination={"ToAddresses": [EMAIL_TO]},
                Message={
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Text": {"Data": message, "Charset": "UTF-8"}
                    }
                }
            )
            self.logger.info(f"Email notification sent: {response['MessageId']}")
        except ClientError as e:
            self.logger.error(f"Failed to send email: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected email error: {e}")
    
    def _send_telegram(self, message: str) -> None:
        """Send Telegram notification."""
        if not self.telegram_token or not self.telegram_chat_id:
            self.logger.debug("Telegram notification skipped - not configured")
            return
        
        # Validate token format (should start with a number followed by colon)
        if ":" not in self.telegram_token:
            self.logger.error("Invalid Telegram bot token format. Should be like: 123456789:ABC-DEF...")
            return
        
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            payload = {
                "chat_id": self.telegram_chat_id,
                "text": message,
                "parse_mode": "HTML"
            }
            
            self.logger.debug(f"Sending Telegram message to chat_id: {self.telegram_chat_id}")
            response = requests.post(url, json=payload, timeout=10)
            
            if response.status_code != 200:
                error_detail = response.text
                self.logger.error(f"Telegram API error ({response.status_code}): {error_detail}")
                
                # Common error explanations
                if "chat not found" in error_detail.lower():
                    self.logger.error("Chat ID not found. Make sure you've started a conversation with the bot first.")
                elif "unauthorized" in error_detail.lower():
                    self.logger.error("Bot token is invalid or bot was blocked.")
                elif "bad request" in error_detail.lower():
                    self.logger.error("Bad request - check your bot token and chat ID format.")
                
                return
            
            response.raise_for_status()
            self.logger.info("Telegram notification sent successfully")
            
        except requests.RequestException as e:
            self.logger.error(f"Failed to send Telegram message: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected Telegram error: {e}")
    
    def send_telegram_image(self, image_path: str, caption: str = "") -> None:
        """Send image via Telegram."""
        if not self.telegram_token or not self.telegram_chat_id:
            self.logger.debug("Telegram image notification skipped - not configured")
            return
        
        # Validate token format
        if ":" not in self.telegram_token:
            self.logger.error("Invalid Telegram bot token format. Should be like: 123456789:ABC-DEF...")
            return
        
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendPhoto"
            
            with open(image_path, 'rb') as image_file:
                files = {'photo': image_file}
                data = {
                    'chat_id': self.telegram_chat_id,
                    'caption': caption,
                    'parse_mode': 'HTML'
                }
                
                self.logger.debug(f"Sending Telegram image to chat_id: {self.telegram_chat_id}")
                response = requests.post(url, files=files, data=data, timeout=30)
                
                if response.status_code != 200:
                    error_detail = response.text
                    self.logger.error(f"Telegram API error ({response.status_code}): {error_detail}")
                    return
                
                response.raise_for_status()
                self.logger.info("Telegram image sent successfully")
                
        except FileNotFoundError:
            self.logger.error(f"Image file not found: {image_path}")
        except requests.RequestException as e:
            self.logger.error(f"Failed to send Telegram image: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected Telegram image error: {e}")