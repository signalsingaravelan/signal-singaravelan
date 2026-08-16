"""Alpaca Trading API client for a single account."""

import os
from datetime import datetime
from typing import Optional

import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetPortfolioHistoryRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import StockLatestTradeRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.common.exceptions import APIError

from algo_trader.logging import get_logger
from algo_trader.utils.config import MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF
from algo_trader.utils.decorators import retry


class OrderRejectionError(Exception):
    """Exception raised when an order is rejected by Alpaca."""

    def __init__(self, message: str, rejection_details: dict = None):
        super().__init__(message)
        self.rejection_details = rejection_details or {}


class AlpacaClient:
    """Alpaca Trading + Market Data API client scoped to one account's credentials."""

    def __init__(self, account):
        self.account_name = account.name
        api_key, api_secret = account.resolve_credentials()
        self.trading = TradingClient(api_key, api_secret, paper=account.paper)
        self.data = StockHistoricalDataClient(api_key, api_secret)
        self.logger = get_logger()

    def initialize(self) -> None:
        """Verify credentials are valid by fetching account details."""
        try:
            account = self._get_account()
            self.logger.info(f"[{self.account_name}] Alpaca client initialized (status={account.status})")
        except APIError as e:
            raise Exception(f"Failed to authenticate with Alpaca: {e}") from e

    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF)
    def _get_account(self):
        return self.trading.get_account()

    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF)
    def get_cash(self) -> float:
        """Available buying power for trading."""
        return float(self._get_account().buying_power)

    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF)
    def get_equity(self) -> float:
        """Total account equity (cash + market value of positions)."""
        return float(self._get_account().equity)

    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF)
    def get_positions(self) -> dict:
        """Current open positions as {symbol: qty}."""
        positions = self.trading.get_all_positions()
        return {p.symbol: float(p.qty) for p in positions}

    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF)
    def get_price(self, symbol: str) -> float:
        """Latest trade price for a symbol."""
        trades = self.data.get_stock_latest_trade(StockLatestTradeRequest(symbol_or_symbols=symbol))
        return float(trades[symbol].price)

    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF, no_retry_exceptions=[OrderRejectionError])
    def submit_notional_buy(self, symbol: str, notional: float):
        """Submit a dollar-denominated market buy order. Returns the submitted Order."""
        try:
            return self.trading.submit_order(MarketOrderRequest(
                symbol=symbol,
                notional=round(notional, 2),
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
            ))
        except APIError as e:
            raise OrderRejectionError(str(e)) from e

    @retry(MAX_RETRY_ATTEMPTS, RETRY_DELAY, RETRY_BACKOFF, no_retry_exceptions=[OrderRejectionError])
    def close_position(self, symbol: str):
        """Liquidate the entire position in a symbol. Returns the submitted Order."""
        try:
            return self.trading.close_position(symbol)
        except APIError as e:
            raise OrderRejectionError(str(e)) from e

    def get_performance(self, notifications_service) -> None:
        """Get account performance for the last 1 year, plot it, and send via Telegram."""
        try:
            history = self.trading.get_portfolio_history(
                GetPortfolioHistoryRequest(period="1Y", timeframe="1D")
            )

            if not history.timestamp or not history.equity:
                self.logger.warning("No portfolio history data to plot")
                return

            dates = [datetime.fromtimestamp(ts) for ts in history.timestamp]
            values = list(history.equity)

            # Simulate buy and hold using beginning balance
            dates_bh_spy, values_bh_spy = self._get_buy_and_hold_series("SPY", values[0], dates[0])
            dates_bh_qqq, values_bh_qqq = self._get_buy_and_hold_series("QQQ", values[0], dates[0])

            account_pct_return = ((values[-1] - values[0]) / values[0]) * 100
            buyhold_spy_pct_return = (
                ((values_bh_spy[-1] - values_bh_spy[0]) / values_bh_spy[0]) * 100 if values_bh_spy else None
            )
            buyhold_qqq_pct_return = (
                ((values_bh_qqq[-1] - values_bh_qqq[0]) / values_bh_qqq[0]) * 100 if values_bh_qqq else None
            )

            fig, ax = plt.subplots(figsize=(16, 9))
            ax.plot(dates, values, linewidth=2, color='gray', label='Account')
            if values_bh_spy:
                ax.plot(dates_bh_spy, values_bh_spy, linewidth=2, color='green', linestyle='--', label='Buy & Hold SPY')
            if values_bh_qqq:
                ax.plot(dates_bh_qqq, values_bh_qqq, linewidth=2, color='blue', linestyle='--', label='Buy & Hold QQQ')

            ax.set_title('Account Performance - Last 1 Year', fontsize=16, fontweight='bold')
            ax.set_xlabel('Date', fontsize=12)
            ax.set_ylabel('Account Equity ($)', fontsize=12)
            ax.yaxis.set_tick_params(labelleft=True, labelright=True)
            ax.tick_params(right=True, labelright=True)
            ax.legend(fontsize=11)
            ax.grid(True, alpha=0.3)
            plt.tight_layout()

            file_name = 'performance.png'
            plt.savefig(file_name, dpi=300, bbox_inches='tight')
            plt.close(fig)

            def _fmt_row(label, pct):
                if pct is None:
                    return f"  {label:<12}{'N/A':>10}"
                emoji = "🟢" if pct >= 0 else "🔴"
                sign = "+" if pct >= 0 else ""
                value = f"{sign}{pct:.2f}%"
                return f"{emoji} {label:<16}{value:>9}"

            caption = (
                "<pre>"
                f"{'Balance'}\n"
                f"{'-'*35}\n"
                f"{'Account':<18}{self.account_name:>13}\n"
                f"{'Net Value':<18}{f'${values[-1]:,.2f}':>13}\n"
                f"{'Buy & Hold SPY':<18}{f'${values_bh_spy[-1]:,.2f}' if values_bh_spy else 'N/A':>13}\n"
                f"{'Buy & Hold QQQ':<18}{f'${values_bh_qqq[-1]:,.2f}' if values_bh_qqq else 'N/A':>13}\n\n"
                f"{'Returns (1Y)'}\n"
                f"{'-'*35}\n"
                f"{_fmt_row('Account', account_pct_return)}\n"
                f"{_fmt_row('Buy & Hold SPY', buyhold_spy_pct_return)}\n"
                f"{_fmt_row('Buy & Hold QQQ', buyhold_qqq_pct_return)}\n"
                "</pre>"
            )

            notifications_service.send_telegram_image(file_name, caption)

            if os.path.exists(file_name):
                os.remove(file_name)

        except Exception as e:
            self.logger.error(f"[{self.account_name}] Failed to get performance data: {e}")

    def _get_buy_and_hold_series(self, symbol: str, starting_balance: float, start_date: datetime):
        """Simulate a buy-and-hold strategy for a symbol starting from start_date.

        Returns (dates, portfolio_values) scaled so the first value equals starting_balance.
        """
        try:
            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame.Day,
                start=start_date,
            )
            bars = self.data.get_stock_bars(request).data.get(symbol, [])
            if len(bars) < 2:
                self.logger.warning(f"Not enough price history for {symbol}")
                return [], []

            dates = [bar.timestamp.replace(tzinfo=None) for bar in bars]
            prices = [float(bar.close) for bar in bars]

            scale = starting_balance / prices[0]
            sim_values = [p * scale for p in prices]

            return dates, sim_values

        except Exception as e:
            self.logger.warning(f"Failed to build buy-and-hold series for {symbol}: {e}")
            return [], []
