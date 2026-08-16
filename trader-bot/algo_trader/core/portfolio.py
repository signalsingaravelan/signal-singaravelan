"""Broker-agnostic position-sizing and allocation logic.

Pure functions: given an account's available cash and its configured ticker
allocation percentages, compute how much to buy of each ticker. Given a
positions snapshot, compute what to liquidate. No broker/API calls here.
"""

from typing import Dict, List, Tuple


def plan_buy(cash: float, allocations: Dict[str, float], min_order_amount: float) -> List[Tuple[str, float]]:
    """Split available cash across tickers per their configured percentages.

    Tickers whose computed dollar amount falls below `min_order_amount` are
    skipped (the rest of the plan still proceeds).
    """
    plan = []
    for symbol, percent in allocations.items():
        amount = round(cash * percent / 100.0, 2)
        if amount >= min_order_amount:
            plan.append((symbol, amount))
    return plan


def plan_sell_all(positions: Dict[str, float]) -> List[str]:
    """Return every symbol currently held with a nonzero position."""
    return [symbol for symbol, qty in positions.items() if qty and qty > 0]
