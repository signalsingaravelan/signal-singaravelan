"""Orchestration tests for Trader, with AlpacaClient fully mocked."""

from unittest.mock import MagicMock, patch

import pytest

from algo_trader.clients import OrderRejectionError
from algo_trader.config.account_config import AccountConfig
from algo_trader.core.trader import Trader
from algo_trader.models import Signal


def make_account(name="taxable", allocations=None):
    return AccountConfig(
        name=name,
        enabled=True,
        paper=True,
        api_key_env="K",
        api_secret_env="S",
        allocations=allocations or {"TQQQ": 100},
    )


@pytest.fixture
def trader():
    t = Trader()
    t.strategy = MagicMock()
    t.trade_logger = MagicMock()
    t.notifications = MagicMock()
    t.logger = MagicMock()
    return t


def test_closed_signal_touches_no_accounts(trader):
    trader.strategy.get_signal.return_value = Signal.CLOSED

    with patch("algo_trader.core.trader.get_enabled_accounts") as mock_get_accounts, \
         patch("algo_trader.core.trader.AlpacaClient") as mock_client_cls:
        trader.execute_trade()

    mock_get_accounts.assert_not_called()
    mock_client_cls.assert_not_called()


def test_bullish_signal_buys_per_account_allocation(trader):
    trader.strategy.get_signal.return_value = Signal.BULLISH
    account = make_account(allocations={"VTI": 50, "VOO": 50})

    mock_client = MagicMock()
    mock_client.get_cash.return_value = 1000.0
    mock_client.get_positions.return_value = {}
    mock_client.submit_notional_buy.return_value = MagicMock(id="order-1")
    mock_client.get_price.return_value = 100.0

    with patch("algo_trader.core.trader.get_enabled_accounts", return_value=[account]), \
         patch("algo_trader.core.trader.AlpacaClient", return_value=mock_client):
        trader.execute_trade()

    assert mock_client.submit_notional_buy.call_count == 2
    calls = {c.args[0]: c.args[1] for c in mock_client.submit_notional_buy.call_args_list}
    assert calls == {"VTI": 500.0, "VOO": 500.0}
    mock_client.wait_for_fill.assert_not_called()

    logged = {c.args[0].symbol: c.args[0] for c in trader.trade_logger.log_trade.call_args_list}
    assert logged.keys() == {"VTI", "VOO"}
    for trade in logged.values():
        assert trade.dollar_amount == 500.0  # exact, it's what we requested
        assert trade.shares == 5.0            # estimated from the $100 mock quote
        assert trade.order_id == "order-1"


def test_bullish_signal_skips_when_cash_below_threshold(trader):
    trader.strategy.get_signal.return_value = Signal.BULLISH
    account = make_account()

    mock_client = MagicMock()
    mock_client.get_cash.return_value = 1.0  # below MIN_CASH_THRESHOLD
    mock_client.get_positions.return_value = {}

    with patch("algo_trader.core.trader.get_enabled_accounts", return_value=[account]), \
         patch("algo_trader.core.trader.AlpacaClient", return_value=mock_client):
        trader.execute_trade()

    mock_client.submit_notional_buy.assert_not_called()


def test_bearish_signal_closes_every_open_position(trader):
    trader.strategy.get_signal.return_value = Signal.BEARISH
    account = make_account()

    mock_client = MagicMock()
    mock_client.get_cash.return_value = 0.0
    mock_client.get_positions.return_value = {"TQQQ": 10.0, "VTI": 3.0}
    mock_client.close_position.return_value = MagicMock(id="order-2")
    mock_client.get_price.return_value = 100.0

    with patch("algo_trader.core.trader.get_enabled_accounts", return_value=[account]), \
         patch("algo_trader.core.trader.AlpacaClient", return_value=mock_client):
        trader.execute_trade()

    assert mock_client.close_position.call_count == 2
    sold_symbols = {c.args[0] for c in mock_client.close_position.call_args_list}
    assert sold_symbols == {"TQQQ", "VTI"}
    mock_client.wait_for_fill.assert_not_called()

    logged = {c.args[0].symbol: c.args[0] for c in trader.trade_logger.log_trade.call_args_list}
    assert logged["TQQQ"].shares == 10.0 and logged["TQQQ"].dollar_amount == 1000.0  # exact shares, estimated $
    assert logged["VTI"].shares == 3.0 and logged["VTI"].dollar_amount == 300.0


def test_bearish_signal_with_no_positions_does_not_sell(trader):
    trader.strategy.get_signal.return_value = Signal.BEARISH
    account = make_account()

    mock_client = MagicMock()
    mock_client.get_cash.return_value = 0.0
    mock_client.get_positions.return_value = {}

    with patch("algo_trader.core.trader.get_enabled_accounts", return_value=[account]), \
         patch("algo_trader.core.trader.AlpacaClient", return_value=mock_client):
        trader.execute_trade()

    mock_client.close_position.assert_not_called()


def test_order_rejection_in_one_account_does_not_stop_others(trader):
    trader.strategy.get_signal.return_value = Signal.BULLISH
    account_a = make_account(name="a")
    account_b = make_account(name="b")

    failing_client = MagicMock()
    failing_client.get_cash.return_value = 1000.0
    failing_client.get_positions.return_value = {}
    failing_client.submit_notional_buy.side_effect = OrderRejectionError("rejected")

    healthy_client = MagicMock()
    healthy_client.get_cash.return_value = 1000.0
    healthy_client.get_positions.return_value = {}
    healthy_client.submit_notional_buy.return_value = MagicMock(id="order-3")
    healthy_client.get_price.return_value = 200.0

    with patch("algo_trader.core.trader.get_enabled_accounts", return_value=[account_a, account_b]), \
         patch("algo_trader.core.trader.AlpacaClient", side_effect=[failing_client, healthy_client]):
        trader.execute_trade()

    healthy_client.submit_notional_buy.assert_called_once()
    trader.trade_logger.log_trade.assert_called_once()
    trader.notifications.send_notification.assert_called()  # rejection notified for account 'a'


def test_no_enabled_accounts_is_a_noop(trader):
    trader.strategy.get_signal.return_value = Signal.BULLISH

    with patch("algo_trader.core.trader.get_enabled_accounts", return_value=[]), \
         patch("algo_trader.core.trader.AlpacaClient") as mock_client_cls:
        trader.execute_trade()

    mock_client_cls.assert_not_called()
