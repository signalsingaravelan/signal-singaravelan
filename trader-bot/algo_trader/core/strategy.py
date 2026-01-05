"""Trading strategy implementation."""

import pytz
import exchange_calendars as xcals
import pandas as pd
import numpy as np

from datetime import datetime
from algo_trader.utils.enums import Signal

class TradingStrategy:
    """Simple trading strategy that returns market signals."""
    
    def get_signal(self) -> Signal:
        try:
            # Download NDX price history since 1985
            url = "https://stooq.com/q/d/l/?s=%5Endx&i=d"
            df = pd.read_csv(url)

            # Indicators
            df["SMA50"] = df["Close"].rolling(50).mean()
            df["Vol_SMA50"] = df["Volume"].rolling(50).mean()
            df["PrevClose"] = df["Close"].shift(1)

            # True Range & ATR
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

            # Today's Signal
            today = df.iloc[-1]

            if today["Bullish"]:
                return Signal.BULLISH
            elif today["BlackDot"]:
                return Signal.BEARISH
            elif today["RedDot"]:
                return Signal.BEARISH
            else:
                return Signal.BEARISH

        except Exception as e:
            self.logger.error(f"Trade execution failed: {e}")
            raise
        
