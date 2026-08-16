# Remove Order-Fill Waiting (Fire-and-Forget Orders)

## Context

The Alpaca migration (already implemented) currently submits an order and then calls `AlpacaClient.wait_for_fill()`, which polls Alpaca's order-status endpoint (up to `ORDER_FILL_TIMEOUT=60s`, every `ORDER_POLL_INTERVAL=3s`) until the order reaches a terminal state, before logging the trade with the actual filled quantity/price.

The deployment plan is now to run this on an EC2 schedule at **8am EST — before market open (9:30am EST)**. Day market orders submitted before the open simply queue and fill once trading starts; polling for a fill at 8am would just burn ~60 seconds waiting on something that can't happen yet. The system should submit the order and move on immediately ("fire-and-forget"), the same way the original IBKR implementation worked.

This reverts one specific decision from the Alpaca migration (the "poll until filled" choice) back toward "fire-and-forget," while keeping everything else (per-account loop, allocation math, synchronous-rejection handling) unchanged.

## What stays the same

`AlpacaClient.submit_notional_buy()` and `close_position()` are unaffected — Alpaca's SDK still raises `APIError` synchronously if an order is rejected *at submission time* (bad symbol, insufficient buying power, etc.), which is already wrapped into `OrderRejectionError` and handled by `trader.py`. That rejection path has nothing to do with polling and is not being touched.

## Files to change

### 1. `trader-bot/algo_trader/clients/alpaca_client.py`
- Delete the `wait_for_fill()` method and the `TERMINAL_ORDER_STATUSES` set.
- Drop the now-unused `import time`, the `OrderStatus` import (only used by the removed set/method), and the `ORDER_FILL_TIMEOUT, ORDER_POLL_INTERVAL` config import.
- No other changes — `submit_notional_buy`, `close_position`, `get_price`, `get_performance`, etc. are untouched.

### 2. `trader-bot/algo_trader/core/trader.py`
- `_handle_bullish_signal`: after `order = client.submit_notional_buy(symbol, amount)`, drop the `wait_for_fill` call. The **dollar amount is already known exactly** (it's what we requested), so only the share count needs an estimate — fetch `client.get_price(symbol)` and compute `amount / price`. Wrap that price lookup in a try/except so a failed quote never blocks logging the trade (the order was already submitted, which is what matters); fall back to `shares=0.0` with a warning if the lookup fails.
- `_handle_bearish_signal`: after `order = client.close_position(symbol)`, drop `wait_for_fill`. The **share count is already known exactly** (`positions[symbol]`, fetched before the loop), so only the dollar amount needs an estimate via `client.get_price(symbol)` — same try/except guard, falling back to `amount=0.0` on a failed lookup.
- `_log_trade`: simplify its signature from `(account, action, symbol, filled_order, requested_amount)` to `(account, action, symbol, order, shares, amount)` — it just persists whatever the caller computed; drop the "use fill data if available, else requested amount" branching since there's no fill data anymore.
- This mirrors exactly how the original IBKR client worked (log the requested/estimated amount immediately, no fill confirmation), so it's a known-good pattern, not new territory.

### 3. `trader-bot/algo_trader/utils/config.py`
- Remove the `ORDER_FILL_TIMEOUT` / `ORDER_POLL_INTERVAL` constants and the "Order Fill Monitoring" section header (no longer referenced anywhere after the above changes).

### 4. `trader-bot/tests/test_trader.py`
- Remove every `mock_client.wait_for_fill.return_value = ...` setup line.
- Add `mock_client.get_price.return_value = <price>` in the bullish/bearish tests that need a share or dollar estimate.
- Update assertions in `test_bullish_signal_buys_per_account_allocation` and `test_bearish_signal_closes_every_open_position` to check the logged `Trade`'s `shares`/`dollar_amount` reflect the new estimate math (via `trader.trade_logger.log_trade.call_args_list`), instead of asserting on `filled_qty`/`filled_avg_price` mock fields that no longer exist in the code path.
- `test_order_rejection_in_one_account_does_not_stop_others`: drop the `wait_for_fill` mock on `healthy_client`, add `get_price` if the buy path needs it.

### 5. `README.md`
- Line ~125: drop "...and order-fill polling timeouts" from the description of `config.py` (that setting no longer exists).
- Line ~157 ("How a Run Works"): replace the "polled until terminal status, logged with actual filled data" sentence with something like: *"Orders are submitted and logged immediately without waiting for a fill — the system is designed to run before market open, so day market orders simply queue until the exchange opens. The logged share count (buys) or dollar amount (sells) is an estimate from the latest quote, not the confirmed fill; check Alpaca's dashboard/order history for actual execution price and time."*

## Trade-off to be aware of

Today's polling also catches an order that's accepted but *later* rejected (e.g., by a post-acceptance risk check) — `wait_for_fill` would surface that as an `OrderRejectionError`. Removing it means only *immediate* submission-time rejections are caught; a later async rejection would go unnoticed until you check Alpaca directly, and the trade log would show a trade that didn't actually happen. This is the same trade-off the original IBKR fire-and-forget design already accepted, and is inherent to not waiting — flagging it so it's a conscious choice, not a surprise. (If it ever matters, a later add-on could be a separate reconciliation step that calls `get_orders()` to true up the log — not part of this change unless you want it.)

## Verification

- `cd trader-bot && python -m pytest tests/` — full suite (including the updated `test_trader.py`) should pass with no network/credentials needed.
- Manual paper-trading spot check: run `python execute-trade.py` (or `docker-compose run --rm trader-bot`) against a paper account before market open with the `strategy.py` test override (`signal = Signal.BULLISH # For testing`) uncommented, confirm the run completes in a couple seconds (no ~60s polling delay) and logs an order immediately, then check Alpaca's paper dashboard once the market opens to confirm it actually filled.
