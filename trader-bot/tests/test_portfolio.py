"""Tests for broker-agnostic allocation logic (algo_trader.core.portfolio)."""

from algo_trader.core.portfolio import plan_buy, plan_sell_all


def test_plan_buy_single_ticker_full_allocation():
    plan = plan_buy(cash=10_000, allocations={"TQQQ": 100}, min_order_amount=1.0)
    assert plan == [("TQQQ", 10_000.0)]


def test_plan_buy_splits_cash_by_percentage():
    plan = plan_buy(
        cash=10_000,
        allocations={"VTI": 20, "VOO": 20, "VUG": 30, "VGT": 15, "QQQ": 15},
        min_order_amount=1.0,
    )
    assert dict(plan) == {
        "VTI": 2000.0,
        "VOO": 2000.0,
        "VUG": 3000.0,
        "VGT": 1500.0,
        "QQQ": 1500.0,
    }


def test_plan_buy_skips_tickers_below_minimum_order_amount():
    plan = plan_buy(cash=10, allocations={"VTI": 95, "QQQ": 5}, min_order_amount=1.0)
    # QQQ's 5% of $10 = $0.50, below the $1 minimum -> skipped, VTI still included
    assert plan == [("VTI", 9.5)]


def test_plan_buy_with_zero_cash_returns_empty_plan():
    plan = plan_buy(cash=0, allocations={"TQQQ": 100}, min_order_amount=1.0)
    assert plan == []


def test_plan_sell_all_returns_every_held_symbol():
    positions = {"TQQQ": 12.5, "VTI": 3.0}
    assert sorted(plan_sell_all(positions)) == ["TQQQ", "VTI"]


def test_plan_sell_all_ignores_zero_and_negative_positions():
    positions = {"TQQQ": 0.0, "VTI": 3.0, "QQQ": -1.0}
    assert plan_sell_all(positions) == ["VTI"]


def test_plan_sell_all_with_no_positions_returns_empty():
    assert plan_sell_all({}) == []
