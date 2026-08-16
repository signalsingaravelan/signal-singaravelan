"""Main trading execution logic."""

from algo_trader.clients import AlpacaClient, OrderRejectionError
from algo_trader.config import AccountConfig, get_enabled_accounts
from algo_trader.core.portfolio import plan_buy, plan_sell_all
from algo_trader.core.strategy import TradingStrategy
from algo_trader.logging import TradeLogger, get_logger
from algo_trader.models import Trade, Signal, Severity
from algo_trader.notifications import NotificationService
from algo_trader.utils.config import MIN_CASH_THRESHOLD, MIN_ORDER_AMOUNT


class Trader:
    """Orchestrates a trading run: one strategy signal, applied independently across
    every enabled Alpaca account per that account's own ticker allocation."""

    def __init__(self):
        self.strategy = TradingStrategy()
        self.trade_logger = TradeLogger()
        self.logger = get_logger()
        self.notifications = NotificationService()

    def execute_trade(self) -> None:
        """Execute the main trading logic across all enabled accounts."""
        try:
            self.logger.info("----------------BEGIN----------------")

            signal = self.strategy.get_signal()
            self.logger.info(f"Signal: {signal.name}")

            if signal == Signal.CLOSED:
                self.logger.info("Market is closed - no trading action taken")
                return

            accounts = get_enabled_accounts()
            if not accounts:
                self.logger.warning("No enabled accounts configured - nothing to trade")
                return

            for account in accounts:
                self._process_account(account, signal)

        except Exception as e:
            self.logger.error(f"Trade execution failed: {e}")
            self.notifications.send_notification("system", Severity.ERROR, f"Trade execution failed: {e}")
        finally:
            self.logger.info("-----------------END-----------------")

    def _process_account(self, account: AccountConfig, signal: Signal) -> None:
        """Handle one account's trading decision. Failures here are isolated so that
        one account's issue doesn't prevent the others from trading."""
        try:
            client = AlpacaClient(account)
            client.initialize()
            self.logger.initialize_cloudwatch(account.name)

            cash = client.get_cash()
            positions = client.get_positions()
            self.logger.info(f"[{account.name}] Cash: ${cash:,.2f} | Positions: {positions}")

            client.get_performance(self.notifications)

            if signal == Signal.BULLISH:
                self._handle_bullish_signal(account, client, cash)
            elif signal == Signal.BEARISH:
                self._handle_bearish_signal(account, client, positions)

        except Exception as e:
            self.logger.error(f"[{account.name}] Failed to process account: {e}")
            self.notifications.send_notification(account.name, Severity.ERROR, f"Account processing failed: {e}")

    def _handle_bullish_signal(self, account: AccountConfig, client: AlpacaClient, cash: float) -> None:
        """Invest available cash across the account's configured tickers.

        Orders are submitted and logged immediately without waiting for a fill —
        this runs before market open, so day market orders simply queue until the
        exchange opens and there's nothing to wait for yet.
        """
        if cash <= MIN_CASH_THRESHOLD:
            self.logger.warning(f"[{account.name}] Insufficient cash for purchase.")
            return

        buy_plan = plan_buy(cash, account.allocations, MIN_ORDER_AMOUNT)
        if not buy_plan:
            self.logger.warning(f"[{account.name}] No ticker allocation met the minimum order amount.")
            return

        for symbol, amount in buy_plan:
            self.logger.info(f"[{account.name}] Placing BUY order for ${amount:.2f} of {symbol}")
            try:
                order = client.submit_notional_buy(symbol, amount)
                shares = self._estimate_shares(client, symbol, amount)
                # amount is exact (it's what we requested); shares is an estimate from the latest quote
                self._log_trade(account, "Buy", symbol, order, shares=shares, amount=amount)
            except OrderRejectionError as e:
                self.logger.error(f"[{account.name}] Buy order rejected for {symbol}: {e}")
                self.notifications.send_notification(account.name, Severity.ERROR, f"Buy order rejected for {symbol}: {e}")

    def _handle_bearish_signal(self, account: AccountConfig, client: AlpacaClient, positions: dict) -> None:
        """Liquidate every open position in the account. Fire-and-forget, same as buys."""
        sell_plan = plan_sell_all(positions)
        if not sell_plan:
            self.logger.info(f"[{account.name}] No positions to sell.")
            return

        for symbol in sell_plan:
            shares = positions[symbol]
            self.logger.info(f"[{account.name}] Placing SELL order for {shares} shares of {symbol}")
            try:
                order = client.close_position(symbol)
                amount = self._estimate_amount(client, symbol, shares)
                # shares is exact (the pre-trade position); amount is an estimate from the latest quote
                self._log_trade(account, "Sell", symbol, order, shares=shares, amount=amount)
            except OrderRejectionError as e:
                self.logger.error(f"[{account.name}] Sell order rejected for {symbol}: {e}")
                self.notifications.send_notification(account.name, Severity.ERROR, f"Sell order rejected for {symbol}: {e}")

    def _estimate_shares(self, client: AlpacaClient, symbol: str, amount: float) -> float:
        """Estimate share count for a notional buy from the latest quote. Never
        raises - a failed quote lookup shouldn't hide that the order was submitted."""
        try:
            price = client.get_price(symbol)
            return amount / price if price else 0.0
        except Exception as e:
            self.logger.warning(f"Failed to estimate shares for {symbol}: {e}")
            return 0.0

    def _estimate_amount(self, client: AlpacaClient, symbol: str, shares: float) -> float:
        """Estimate dollar amount for a share-based sell from the latest quote. Never
        raises - a failed quote lookup shouldn't hide that the order was submitted."""
        try:
            return shares * client.get_price(symbol)
        except Exception as e:
            self.logger.warning(f"Failed to estimate amount for {symbol}: {e}")
            return 0.0

    def _log_trade(self, account: AccountConfig, action: str, symbol: str, order, shares: float, amount: float) -> None:
        """Record a submitted (not necessarily filled) trade."""
        trade = Trade(
            account_id=account.name,
            action=action,
            symbol=symbol,
            dollar_amount=amount,
            shares=shares,
            order_id=str(order.id),
        )
        self.trade_logger.log_trade(trade)
