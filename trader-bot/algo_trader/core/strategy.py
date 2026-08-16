"""
Nasdaq 100 Index Monitor with IBD Follow Through Day (FTD)
Ticker - QQQ

IBD Follow Through Day (FTD) Rules:
1. Track rally attempt from recent low after 52-week high
2. Day 1: Index closes higher than prior day after recent low
3. Rally continues as long as index doesn't undercut the low
4. FTD occurs on Day 4+ when:
   - QQQ gains 1.7%+ and
   - Volume > Prior Day

*** Bearish Signals ***
Black Dot - ⚫ - Sudden heavy selling & volatility (short-term bearish risk like 2020 COVID or 2025 liberation day)
- Today's close < 50-day moving average.
- All of the following occur on the same day at least once in the past 5 trading days:
  - True Range > 2 × Average True Range (means volatility is spiking)
  - Closing Range < 10% (price closes near the low of the day)
  - Volume > 50-day moving average (high selling pressure)

Red Dot - 🔴 - Ongoing weakness (medium-term bearish risk like 2022 bear market).
- Today's close < 50-day moving average.
- Up/Down Volume Ratio < 0.9 for 3 or more times in the past 5 trading days.
  (more volume on down days than up days)

*** Bullish Signals ***
Bullish-1:
- No black/red dot today
- FTD occurred in past 10 days
	
Bullish-2:
- No black/red dot today
- No black/red dots in past 7 days

Bullish: Bullish-1 or Bullish-2

"""
import numpy as np
import pandas as pd
import pandas_market_calendars as mcal

import os
import requests

import boto3
from botocore.exceptions import ClientError

from algo_trader.logging import get_logger
from algo_trader.models import Signal, Severity
from algo_trader.notifications import NotificationService

from algo_trader.utils.config import MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF, S3_BUCKET_NAME, S3_REGION, S3_KEY_PREFIX, MASSIVE_API_KEY
from algo_trader.utils.decorators import retry

class TradingStrategy:

    def __init__(self):
        self.logger = get_logger()
        self.notifications = NotificationService()
        self.s3 = boto3.client("s3", region_name=S3_REGION)
        self.bucket_name = S3_BUCKET_NAME
        self._bucket_initialized = False

    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF)
    def get_signal(self) -> Signal:
        """Check market health using QQQ price and volume history.

        Computed once per run, independent of any trading account — the same
        market signal is applied to every configured account.
        """
        try:
            self._initialize_bucket()

            today = pd.Timestamp.now(tz='US/Eastern').date()
            # today = date(2026, 3, 30) # override for testing purposes

            nyse = mcal.get_calendar('NYSE')
            schedule = nyse.schedule(today, today)
            if schedule.empty:
                signal = Signal.CLOSED
                message = f"Market Signal: {signal.name} as of {today}"
                self.logger.info(message)
                self.notifications.send_notification("N/A", Severity.INFO, message)
                return signal

            self.logger.info("Loading QQQ price history from S3")
            csv_filename = "qqq-price-history.csv"
            df = self._load_csv_from_s3(csv_filename)

            # Determine the latest completed trading session
            recent_sessions = nyse.schedule(
                start_date=pd.Timestamp.now(tz='US/Eastern').date() - pd.Timedelta(days=10),
                end_date=pd.Timestamp.now(tz='US/Eastern').date()
            )

            # Exclude today if market is still open or hasn't opened yet
            recent_sessions = recent_sessions[
                recent_sessions.index.date < pd.Timestamp.now(tz='US/Eastern').date()
            ]

            latest_session = recent_sessions.index[-1].date()
            self.logger.info(f"Latest completed trading session: {latest_session}")

            df['Date'] = pd.to_datetime(df['Date'])
            last_date_in_df = df['Date'].iloc[-1].date()
            self.logger.info(f"Last date in price history: {last_date_in_df}")

            # Fetch incremental data if the latest session is not in the DataFrame
            if last_date_in_df < latest_session:
                self.logger.info(f"Price history is stale — fetching latest data from Massive.com")

                try:
                    from_date = (last_date_in_df + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
                    to_date = latest_session.strftime("%Y-%m-%d")

                    url = (
                        f"https://api.massive.com/v2/aggs/ticker/QQQ/range/1/day"
                        f"/{from_date}/{to_date}"
                        f"?adjusted=true&apiKey={MASSIVE_API_KEY}"
                    )
                    response = requests.get(url, timeout=10)
                    response.raise_for_status()
                    data = response.json()

                    results = data.get("results", [])
                    if results:
                        new_df = pd.DataFrame(results)
                        # Massive fields: t (ms epoch), o, h, l, c, v
                        new_df["Date"] = pd.to_datetime(new_df["t"], unit="ms", utc=True).dt.tz_convert("US/Eastern").dt.normalize().dt.tz_localize(None)
                        new_df = new_df.rename(columns={"o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume"})
                        new_df = new_df[["Date", "Open", "High", "Low", "Close", "Volume"]]
                        new_df["Volume"] = new_df["Volume"].round().astype(int)

                        df = pd.concat([df, new_df], ignore_index=True).drop_duplicates(subset="Date")
                        df = df.sort_values("Date").reset_index(drop=True)
                        self.logger.info(f"Appended {len(new_df)} new row(s) from Massive.com")
                    else:
                        self.logger.info("No new rows returned from Massive.com")
                except Exception as e:
                    self.logger.error(f"Failed to fetch incremental data from Massive.com: {e}")

            # Ideally the bot should run before market open.
            # If it runs after market open, this step removes the row for the current date.
            if df['Date'].iloc[-1].date() == today:
                df = df.iloc[:-1]

            df.to_csv(csv_filename, index=False)

            # Indicators
            df["SMA50"] = df["Close"].rolling(50).mean()
            df["VolSMA50"] = df["Volume"].rolling(50).mean()
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
            cond_day = (df["TR"] > 2 * df["ATR"]) & (df["CR"] < 0.10) & (df["Volume"] > df["VolSMA50"])
            black_cond = cond_day.rolling(5).max() > 0
            df["BlackDot"] = (df["Close"] < df["SMA50"]) & black_cond

            # Red Dot
            udvr_count = (df["UDVR"] < 0.9).rolling(5).sum()
            df["RedDot"] = (df["Close"] < df["SMA50"]) & (udvr_count >= 3)

            df["Bearish"] = df["BlackDot"] | df["RedDot"]
            df["Bullish"] = False

            if ~(df["Bearish"].iloc[-1]):

                # IBD Follow Through Day (FTD) Implementation
                # Step 1: Find 52-week highs
                df["High52W"] = df["High"].rolling(252).max()
                df["Is52WHigh"] = df["High"] == df["High52W"]
                
                # Step 2: Find recent lows after 52-week highs
                # Mark periods after 52-week highs
                df["After52WHigh"] = False
                for i in range(1, len(df)):

                    if df.iloc[i-1]["Is52WHigh"]:
                        df.iloc[i:, df.columns.get_loc("After52WHigh")] = True

                    # Reset if we hit a new 52-week high
                    if df.iloc[i]["Is52WHigh"]:
                        df.iloc[i, df.columns.get_loc("After52WHigh")] = False
                
                # Find lowest low in past 10 days
                df["Low10D"] = df["Low"].rolling(10).min()
                df["IsRecentLow"] = (df["Low"] == df["Low10D"]) & df["After52WHigh"]
                
                # Step 3: Track rally attempts from recent lows
                df["InRally"] = False
                df["RallyDay"] = 0
                df["RallyLow"] = np.nan
                df["FirstFTDLow"] = np.nan

                rally_day = 0
                rally_low = np.nan
                in_rally = False
                first_ftd_low = np.nan

                for i in range(1, len(df)):
                    prev_close = df.iloc[i-1]["Close"]
                    curr_close = df.iloc[i]["Close"]
                    curr_low = df.iloc[i]["Low"]

                    prev_volume = df.iloc[i-1]["Volume"]
                    curr_volume = df.iloc[i]["Volume"]
                    price_chg_pct = (curr_close - prev_close) / prev_close * 100

                    # Start new rally attempt if we close higher after a recent low
                    if df.iloc[i-1]["IsRecentLow"] and curr_close > prev_close:
                        rally_day = 1
                        rally_low = df.iloc[i-1]["Low"]
                        in_rally = True
                        first_ftd_low = np.nan

                    # Continue rally if we don't undercut the rally low
                    elif in_rally and curr_close >= rally_low:
                        rally_day += 1

                    # End rally if we undercut the low
                    elif in_rally and curr_close < rally_low:
                        rally_day = 0
                        rally_low = np.nan
                        in_rally = False
                        first_ftd_low = np.nan

                    # Track first FTD low of this rally
                    if in_rally and np.isnan(first_ftd_low):
                        is_ftd = rally_day >= 4 and price_chg_pct >= 1.7 and curr_volume > prev_volume
                        if is_ftd:
                            first_ftd_low = curr_low

                    df.iloc[i, df.columns.get_loc("InRally")] = in_rally
                    df.iloc[i, df.columns.get_loc("RallyDay")] = rally_day
                    df.iloc[i, df.columns.get_loc("RallyLow")] = rally_low
                    df.iloc[i, df.columns.get_loc("FirstFTDLow")] = first_ftd_low
                
                # Step 4: Identify FTD (Day 4+ with 1.7%+ gain and volume > prior day)
                df["FirstFTDLow"] = df["FirstFTDLow"].where(df["InRally"]).ffill()
                df["PrevVolume"] = df["Volume"].shift(1)
                df["PriceChangePct"] = (df["Close"] - df["PrevClose"]) / df["PrevClose"] * 100
                
                df["FTD"] = (
                    (df["RallyDay"] >= 4) &
                    (df["PriceChangePct"] >= 1.7) &
                    (df["Volume"] > df["PrevVolume"])
                )

                df["FTDLastX"] = df["FTD"].rolling(10).max()
                df["AnyDotsLastX"] = (df["Bearish"]).rolling(7).max()
                
                # Initialize bullish columns
                df["Bullish-1"] = False
                df["Bullish-2"] = False
                
                # Bullish-1:
                # FTD occurred in past X days and Close > First FTD Low
                df.loc[(df["FTDLastX"] > 0) & (df["Close"] > df["FirstFTDLow"]), "Bullish-1"] = True
                
                # Bullish-2:
                # No black/red dots in past X days
                df.loc[df["AnyDotsLastX"] == 0, "Bullish-2"] = True

                # Bullish:
                df["Bullish"] = df["Bullish-1"] | df["Bullish-2"]

            # Save Excel file locally
            excel_filename = "market-outlook.xlsx"
            df.to_excel(excel_filename, index=False)
            
            # Upload both files to S3
            csv_s3_key = f"{S3_KEY_PREFIX}{csv_filename}"
            excel_s3_key = f"{S3_KEY_PREFIX}{excel_filename}"
            
            csv_uploaded = self._upload_file_to_s3(csv_filename, csv_s3_key)
            excel_uploaded = self._upload_file_to_s3(excel_filename, excel_s3_key)
            
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

            if last_row["Bullish"]:
                signal = Signal.BULLISH
            else:
                signal = Signal.BEARISH

            # For testing
            # signal = Signal.BULLISH

            message = f"Market Signal: {signal.name} as of {asof_date}"
            self.logger.info(message)
            self.notifications.send_notification("N/A", Severity.INFO, message)
            return signal

        except Exception as e:
            self.logger.error(f"Failed to get market signal: {e}")
            raise  # Re-raise the original exception

    def _initialize_bucket(self) -> None:
        """Initialize the shared market-data bucket on first use."""
        if self._bucket_initialized:
            return

        self.bucket_name = f"{S3_BUCKET_NAME}-market-data"
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
    def _load_csv_from_s3(self, s3_key: str) -> pd.DataFrame:
        """Download a CSV from S3 and return it as a DataFrame."""
        try:
            response = self.s3.get_object(Bucket=self.bucket_name, Key=s3_key)
            df = pd.read_csv(response["Body"])
            self.logger.info(f"Loaded {len(df)} rows from s3://{self.bucket_name}/{s3_key}")
            return df
        except ClientError as e:
            self.logger.error(f"Failed to load CSV from S3 ({s3_key}): {e}")
            raise

    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF)
    def _upload_file_to_s3(self, local_file_path: str, s3_key: str) -> bool:
        """Upload a local file to S3."""
        try:
            self.s3.upload_file(local_file_path, self.bucket_name, s3_key)
            return True
        except ClientError as e:
            self.logger.error(f"Failed to upload {local_file_path} to S3: {e}")
            return False
