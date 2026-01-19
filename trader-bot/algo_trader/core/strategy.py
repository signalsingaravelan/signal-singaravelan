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
import sys
import numpy as np
import pandas as pd
from datetime import datetime

import pytz
import exchange_calendars as xcals

from algo_trader.clients import IBKRClient
from algo_trader.logging import get_logger
from algo_trader.notifications import NotificationService
from algo_trader.utils.enums import Signal, Severity

from algo_trader.utils.config import MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF
from algo_trader.utils.decorators import retry

class TradingStrategy:

    def __init__(self):
        self.client = IBKRClient()
        self.client.check_auth()
        self.account_id = self.client.get_account_id()

        self.logger = get_logger()
        self.notifications = NotificationService()

    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF)
    def get_signal(self) -> Signal:
        try:

            # Check if market is open today
            est = pytz.timezone('US/Eastern')
            current_date = datetime.now(est).date()
            nyse = xcals.get_calendar("XNYS")

            if not nyse.is_session(current_date):
                return Signal.CLOSED

            # Download NDX price history since 1985
            df = self._download_price_history()
            df.to_csv("ndx-price-history.csv", index=False)

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

            df.to_excel("market-outlook.xlsx", index=False)

            # Today's Signal
            today = df.iloc[-1]

            if today["Bullish"]:
                return Signal.BULLISH
            elif today["BlackDot"] or today["RedDot"]:
                return Signal.BEARISH
            else:
                return Signal.NEUTRAL

        except Exception as e:
            error_msg = f"Get market signal failed. {e}"
            self.logger.error(error_msg)
            self.notifications.send_notification(self.account_id, Severity.ERROR, error_msg)
            sys.exit(0)

    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF)
    def _download_price_history(self):
        url = "https://stooq.com/q/d/l/?s=%5Endx&i=d"
        self.logger.info(f"Downloading NDX price history.")

        try:
            return pd.read_csv(url)
        except Exception as e:
            error_msg = f"NDX price history download failed. {e}"
            self.logger.error(error_msg)
            raise Exception(error_msg)

