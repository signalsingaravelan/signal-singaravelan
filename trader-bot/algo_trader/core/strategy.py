"""
Nasdaq 100 Index Monitor v1

Bearish - if there is a black or red dot today.
Neutral - if there was a black or red dot in the past 10 trading days.
Bullish - if there are no black or red dots in the past 10 trading days.

Black Dot - ⚫ - Sudden heavy selling & volatility (short-term bearish risk like 2020 COVID or 2025 liberation day)
- Today's close < 50-day moving average.
- All of the following occur on the same day at least once in the past 5 trading days:
  - True Range > 1.5 × Average True Range (means volatility is spiking)
  - Closing Range < 10% (price closes near the low of the day)
  - Volume > 50-day moving average (high selling pressure)

Red Dot - 🔴 - Ongoing weakness (medium-term bearish risk like 2022 bear market).
- Today's close < 50-day moving average.
- Up/Down Volume Ratio < 1 for 3 or more times in the past 5 trading days.
  (more volume on down days than up days)

Black dots signal strong downside pressure with high volume and volatility.
Red dots indicate persistent selling pressure and weaker market sentiment.

"""
import numpy as np
import pandas as pd
import pandas_market_calendars as mcal
from datetime import date
import os

import boto3
from botocore.exceptions import ClientError

from algo_trader.logging import get_logger
from algo_trader.models import Signal, Severity
from algo_trader.notifications import NotificationService

from algo_trader.utils.config import MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF, S3_BUCKET_NAME, S3_REGION, S3_KEY_PREFIX
from algo_trader.utils.decorators import retry

class TradingStrategy:

    def __init__(self):
        self.logger = get_logger()
        self.notifications = NotificationService()
        self.s3 = boto3.client("s3", region_name=S3_REGION)
        self.bucket_name = S3_BUCKET_NAME
        self._bucket_initialized = False

    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF)
    def get_signal(self, account_id: str) -> Signal:
        """Check market health using NDX price and volume history."""
        try:
            # Initialize S3 bucket with account ID
            self._initialize_bucket(account_id)

            today = pd.Timestamp.now(tz='US/Eastern').date()
            # today = date(2026, 1, 30) # override for testing purposes

            nyse = mcal.get_calendar('NYSE')
            schedule = nyse.schedule(today, today)
            if schedule.empty:
                signal = Signal.CLOSED
                message = f"Market Signal: {signal.name} as of {today}"
                self.logger.info(message)
                self.notifications.send_notification(account_id, Severity.INFO, message)
                return signal

            self.logger.info(f"Downloading NDX price history")
            url = "https://stooq.com/q/d/l/?s=%5Endx&i=d"
            df = pd.read_csv(url)
            
            # Save CSV file locally
            csv_filename = "ndx-price-history.csv"
            df.to_csv(csv_filename, index=False)

            # Ideally the bot should run before market open.
            # If it runs after market open, this step removes the row for the current date.
            df['Date'] = pd.to_datetime(df['Date'])
            if df['Date'].iloc[-1].date() == today:
                df = df.iloc[:-1]

            # Indicators
            df["SMA50"] = df["Close"].rolling(50).mean()
            df["Vol_SMA50"] = df["Volume"].rolling(50).mean()
            df["PrevClose"] = df["Close"].shift(1)

            # True Range & Average True Range
            df["TR"] = df[["High", "PrevClose"]].max(axis=1) - df[["Low", "PrevClose"]].min(axis=1)
            df["ATR"] = df["TR"].rolling(14).mean()

            # Closing Range
            df["CR"] = (df["Close"] - df["Low"]) / (df["High"] - df["Low"])
            df["CR"] = df["CR"].replace([np.inf, -np.inf], np.nan)

            # Up/Down Volume Ratio
            df["UpVol"] = np.where(df["Close"] > df["PrevClose"], df["Volume"], 0)
            df["DownVol"] = np.where(df["Close"] < df["PrevClose"], df["Volume"], 0)
            df["UDVR"] = df["UpVol"].rolling(50).sum() / df["DownVol"].rolling(50).sum()

            # Black Dot
            cond_day = (df["TR"] > 1.5 * df["ATR"]) & (df["CR"] < 0.10) & (df["Volume"] > df["Vol_SMA50"])
            black_cond = cond_day.rolling(5).max() > 0
            df["BlackDot"] = (df["Close"] < df["SMA50"]) & black_cond

            # Red Dot
            udvr_count = (df["UDVR"] < 1).rolling(5).sum()
            df["RedDot"] = (df["Close"] < df["SMA50"]) & (udvr_count >= 3)

            # Bullish
            any_dots_last10 = (df["BlackDot"] | df["RedDot"]).rolling(10).max()
            df["Bullish"] = (any_dots_last10 == 0)

            # Save Excel file locally
            excel_filename = "market-outlook.xlsx"
            df.to_excel(excel_filename, index=False)
            
            # Upload both files to S3
            csv_s3_key = f"{S3_KEY_PREFIX}{csv_filename}"
            excel_s3_key = f"{S3_KEY_PREFIX}{excel_filename}"
            
            csv_uploaded = self._upload_file_to_s3(csv_filename, csv_s3_key)
            excel_uploaded = self._upload_file_to_s3(excel_filename, excel_s3_key)
            
            if not csv_uploaded:
                self.logger.warning(f"Failed to upload {csv_filename} to S3")
            if not excel_uploaded:
                self.logger.warning(f"Failed to upload {excel_filename} to S3")
            
            # Clean up local files only if S3 upload was successful
            try:
                if csv_uploaded and os.path.exists(csv_filename):
                    os.remove(csv_filename)
                if excel_uploaded and os.path.exists(excel_filename):
                    os.remove(excel_filename)
            except OSError as e:
                self.logger.warning(f"Failed to clean up local files: {e}")

            # Determine market signal
            last_row = df.iloc[-1]
            asof_date = last_row["Date"].date()

            # Handle potential NaN values in signal calculations
            bullish = last_row["Bullish"] if pd.notna(last_row["Bullish"]) else False
            black_dot = last_row["BlackDot"] if pd.notna(last_row["BlackDot"]) else False
            red_dot = last_row["RedDot"] if pd.notna(last_row["RedDot"]) else False

            if bullish:
                signal = Signal.BULLISH
            elif black_dot or red_dot:
                signal = Signal.BEARISH
            else:
                signal = Signal.NEUTRAL

            message = f"Market Signal: {signal.name} as of {asof_date}"
            self.logger.info(message)
            self.notifications.send_notification(account_id, Severity.INFO, message)
            return signal

        except Exception as e:
            self.logger.error(f"Failed to get market signal: {e}")
            raise  # Re-raise the original exception

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
                raise  # Re-raise non-404 errors

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
            raise  # Re-raise the exception

    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF)
    def _upload_file_to_s3(self, local_file_path: str, s3_key: str) -> bool:
        """Upload a local file to S3."""
        try:
            self.s3.upload_file(local_file_path, self.bucket_name, s3_key)
            return True
        except ClientError as e:
            self.logger.error(f"Failed to upload {local_file_path} to S3: {e}")
            return False
