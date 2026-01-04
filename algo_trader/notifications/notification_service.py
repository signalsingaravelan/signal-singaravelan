"""Notification service for trade alerts via email and Telegram."""

import json
import os
from datetime import datetime
from typing import Optional

import boto3
import requests
from botocore.exceptions import ClientError

from algo_trader.logging import get_logger
from algo_trader.utils.config import (
    EMAIL_FROM, EMAIL_TO, EMAIL_REGION,
    TELEGRAM_CHAT_ID, SECRETS_MANAGER_SECRET_NAME, SECRETS_MANAGER_REGION
)

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
        """Fetch Telegram bot token from AWS Secrets Manager."""
        try:
            # Create a Secrets Manager client
            secrets_client = boto3.client("secretsmanager", region_name=SECRETS_MANAGER_REGION)
            
            # Retrieve the secret
            response = secrets_client.get_secret_value(SecretId=SECRETS_MANAGER_SECRET_NAME)
            
            # Parse the secret JSON
            secret_data = json.loads(response["SecretString"])
            
            # Extract the Telegram bot token
            telegram_token = secret_data.get("TelegramBotToken")
            
            if telegram_token:
                self.logger.info("Successfully retrieved Telegram bot token from Secrets Manager")
                return telegram_token
            else:
                self.logger.error("TelegramBotToken key not found in secret")
                return None
                
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "ResourceNotFoundException":
                self.logger.error(f"Secret '{SECRETS_MANAGER_SECRET_NAME}' not found in Secrets Manager")
            elif error_code == "InvalidRequestException":
                self.logger.error("Invalid request to Secrets Manager")
            elif error_code == "InvalidParameterException":
                self.logger.error("Invalid parameter for Secrets Manager request")
            elif error_code == "DecryptionFailureException":
                self.logger.error("Failed to decrypt secret from Secrets Manager")
            elif error_code == "InternalServiceErrorException":
                self.logger.error("Internal error in Secrets Manager service")
            else:
                self.logger.error(f"Secrets Manager error: {e}")
            return None
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse secret JSON: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error retrieving Telegram token: {e}")
            return None
    
    def send_trade_notification(self, account_id: str, action: str, symbol: str,
                              dollar_amount: float, shares: float, order_id: str) -> None:
        """Send trade notification via email and Telegram."""
        message = self._format_trade_message(
            account_id, action, symbol, dollar_amount, shares, order_id
        )
        
        # Send email notification
        self._send_email(f"Trade Executed: {action} {symbol}", message)
        
        # Send Telegram notification
        self._send_telegram(message)
    
    def _format_trade_message(self, account_id: str, action: str, symbol: str,
                            dollar_amount: float, shares: float, order_id: str) -> str:
        """Format trade information into a readable message."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        return f"""🤖 Trade Executed

📅 Time: {timestamp}
👤 Account: {account_id}
📊 Action: {action}
🏷️ Symbol: {symbol}
💰 Amount: ${dollar_amount:.2f}
📈 Shares: {shares:.2f}
🆔 Order ID: {order_id}"""
    
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
    
    def send_test_notification(self) -> None:
        """Send a test notification to verify configuration."""
        test_message = f"""🧪 Test Notification

This is a test message from your trading bot.
Time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

If you receive this, notifications are working correctly! 🎉"""
        
        self._send_email("Trading Bot Test Notification", test_message)
        self._send_telegram(test_message)
    
    def test_telegram_config(self) -> None:
        """Test Telegram configuration and provide setup guidance."""
        print("🔧 Testing Telegram Configuration...")
        print(f"Bot Token: {'✓ Retrieved from Secrets Manager' if self.telegram_token else '✗ Failed to retrieve'}")
        print(f"Chat ID: {'✓ Set' if self.telegram_chat_id else '✗ Missing'}")
        
        if not self.telegram_token:
            print("\n❌ Telegram Bot Token could not be retrieved from Secrets Manager!")
            print("Please ensure:")
            print(f"1. Secret '{SECRETS_MANAGER_SECRET_NAME}' exists in AWS Secrets Manager")
            print("2. The secret contains a key 'TelegramBotToken' with your bot token")
            print("3. Your EC2 instance has permission to access Secrets Manager")
            print("\nRequired IAM permissions:")
            print("- secretsmanager:GetSecretValue")
            return
        
        if not self.telegram_chat_id:
            print("\n❌ Telegram Chat ID is missing!")
            print("To get your Chat ID:")
            print("1. Start a conversation with your bot")
            print("2. Send any message to the bot")
            print("3. Visit: https://api.telegram.org/bot{YOUR_BOT_TOKEN}/getUpdates")
            print("4. Look for 'chat':{'id': YOUR_CHAT_ID}")
            print("5. Update TELEGRAM_CHAT_ID in config.py")
            return
        
        # Test the bot by getting bot info
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/getMe"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                bot_info = response.json()
                if bot_info.get("ok"):
                    bot_name = bot_info["result"]["username"]
                    print(f"✅ Bot token is valid! Bot name: @{bot_name}")
                    
                    # Now test sending a message
                    self._send_telegram("🧪 Telegram configuration test successful!")
                else:
                    print("❌ Bot token is invalid")
            else:
                print(f"❌ Failed to validate bot token: {response.status_code}")
                print(f"Response: {response.text}")
                
        except Exception as e:
            print(f"❌ Error testing Telegram config: {e}")