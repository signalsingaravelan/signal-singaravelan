"""Trade logging functionality for Excel reporting with S3 storage."""

import io
from datetime import datetime
from typing import Optional

import boto3
import pandas as pd
from botocore.exceptions import ClientError

from algo_trader.logging.cloudwatch_logger import get_logger
from algo_trader.models import Trade
from algo_trader.notifications import NotificationService
from algo_trader.utils.config import S3_BUCKET_NAME, S3_REGION, S3_KEY_PREFIX


class TradeLogger:
    """Logs trade information to Excel files stored in S3."""
    
    FILENAME_TEMPLATE = "{account_id}-order-history.xlsx"
    EXCEL_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    
    def __init__(self):
        self.logger = get_logger()
        self.notifications = NotificationService()
        self.s3 = boto3.client("s3", region_name=S3_REGION)
        self.bucket_name = S3_BUCKET_NAME
        self._bucket_initialized = False

    # -------------------------------------------------------------------------
    # Public methods
    # -------------------------------------------------------------------------

    def log_trade(self, trade: Trade) -> str:
        """Log trade to S3 and send notifications. Returns order ID."""
        # Initialize bucket with account ID on first trade
        self._initialize_bucket(trade.account_id)

        # Ensure trade has an order ID
        if trade.order_id is None:
            trade.order_id = f"ORD_{trade.timestamp.strftime('%Y%m%d_%H%M%S')}"
        
        try:
            s3_key = self._get_s3_key(trade.account_id)
            existing_df = self._download_excel(s3_key)
            updated_df = pd.concat([existing_df, pd.DataFrame([trade.to_dict()])], ignore_index=True)
            self._upload_excel(updated_df, s3_key)

            self.logger.info(f"Trade logged to s3://{self.bucket_name}/{s3_key}")
            self.notifications.send_trade_notification(trade)
        except Exception as e:
            self.logger.error(f"Failed to log trade: {e}")
        
        return trade.order_id

    def get_trade_history(self, account_id: str) -> Optional[pd.DataFrame]:
        """Retrieve trade history DataFrame for an account."""
        self._initialize_bucket(account_id)
        try:
            df = self._download_excel(self._get_s3_key(account_id))
            return df if not df.empty else None
        except Exception as e:
            self.logger.error(f"Failed to get trade history: {e}")
            return None

    def download_to_file(self, account_id: str, local_path: str) -> bool:
        """Download trade history Excel file to local path."""
        self._initialize_bucket(account_id)
        try:
            self.s3.download_file(self.bucket_name, self._get_s3_key(account_id), local_path)
            self.logger.info(f"Downloaded trade history to {local_path}")
            return True
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            self.logger.error(f"S3 download failed ({error_code}): {e}")
            return False

    def test_notifications(self) -> None:
        """Send test notifications to verify configuration."""
        self.notifications.send_test_notification()

    # -------------------------------------------------------------------------
    # Private methods
    # -------------------------------------------------------------------------

    def _get_s3_key(self, account_id: str) -> str:
        """Generate S3 key for account's trade history file."""
        return f"{S3_KEY_PREFIX}{self.FILENAME_TEMPLATE.format(account_id=account_id)}"

    def _initialize_bucket(self, account_id: str) -> None:
        """Initialize bucket with account-specific name on first use."""
        if self._bucket_initialized:
            return

        # Append account ID to bucket name (lowercase for S3 naming rules)
        self.bucket_name = f"{S3_BUCKET_NAME}-{account_id.lower()}"
        self._ensure_bucket_exists()
        self._bucket_initialized = True

    def _ensure_bucket_exists(self) -> None:
        """Create S3 bucket if it doesn't exist."""
        try:
            self.s3.head_bucket(Bucket=self.bucket_name)
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                self._create_bucket()
            else:
                self.logger.error(f"Error checking bucket: {e}")

    def _create_bucket(self) -> None:
        """Create S3 bucket with appropriate configuration."""
        try:
            # us-east-1 doesn't need LocationConstraint
            if S3_REGION == "us-east-1":
                self.s3.create_bucket(Bucket=self.bucket_name)
            else:
                self.s3.create_bucket(
                    Bucket=self.bucket_name,
                    CreateBucketConfiguration={"LocationConstraint": S3_REGION}
                )
            self.logger.info(f"Created S3 bucket: {self.bucket_name}")
        except ClientError as e:
            self.logger.error(f"Failed to create bucket: {e}")

    def _download_excel(self, s3_key: str) -> pd.DataFrame:
        """Download Excel file from S3, returns empty DataFrame if not found."""
        try:
            response = self.s3.get_object(Bucket=self.bucket_name, Key=s3_key)
            return pd.read_excel(io.BytesIO(response["Body"].read()))
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return pd.DataFrame()
            raise

    def _upload_excel(self, df: pd.DataFrame, s3_key: str) -> None:
        """Upload DataFrame as Excel file to S3."""
        buffer = io.BytesIO()
        df.to_excel(buffer, index=False, engine="openpyxl")
        buffer.seek(0)
        
        self.s3.put_object(
            Bucket=self.bucket_name,
            Key=s3_key,
            Body=buffer.getvalue(),
            ContentType=self.EXCEL_CONTENT_TYPE
        )