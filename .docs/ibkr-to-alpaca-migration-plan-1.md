# Migrate Trading System from IBKR to Alpaca — Migration Plan

## Context

This repo (`signal-singaravelan`) runs a small automated trading bot: a cron/`docker-compose run` invocation once per day evaluates a NASDAQ-100 technical-analysis strategy (`strategy.py`) and, on a bullish/bearish signal, buys or sells a single hardcoded symbol (`TQQQ`) in a single IBKR account via the IBKR Client Portal Web API (proxied through a local `ibeam`/IB Gateway Docker sidecar).

Per `migrate-ibkr-to-alpaca.md`, the goal is to replace IBKR with Alpaca, generalize the system to support **multiple independent Alpaca accounts** (e.g. taxable, Traditional IRA, Roth IRA), each with its **own ticker allocation percentages**, while leaving `strategy.py`'s signal logic untouched and cleanly separating **Strategy → Portfolio/Allocation → Broker Execution**. This plan is for review only — no code will change until it's approved.

User decisions already confirmed (via clarifying questions):
- **Buy allocation**: cash-only, no rebalance — every bullish signal invests 100% of an account's available cash per its configured percentages, regardless of current position mix (matches today's single-symbol behavior, extended to multiple tickers).
- **Order monitoring**: poll Alpaca for order status after submission and log the actual filled qty/price once the order reaches a terminal state (bounded timeout).
- **Sell scope**: a bearish signal liquidates **every open position** in the account, not just the configured tickers.
- **Paper vs live**: every account config defaults to `paper: true`; live trading is an explicit opt-in per account.

---

## A. Current Architecture

```
trader-bot/
  execute-trade.py                     # entry point → Trader().execute_trade()
  algo_trader/
    core/
      trader.py                        # orchestrator: signal → size order → call broker (single account, single symbol)
      strategy.py                      # NASDAQ-100 / IBD Follow-Through-Day signal generator (broker-independent)
    clients/
      ibkr_client.py                   # IBKR Client Portal Web API wrapper (REST via local ibeam gateway)
    models/
      enums.py                         # Signal{BULLISH,BEARISH,CLOSED}, Severity
      trade.py                         # Trade dataclass
    logging/
      cloudwatch_logger.py             # console + CloudWatch, log group keyed by account_id
      trade_logger.py                  # trade history Excel round-tripped through S3, keyed by account_id
    notifications/
      notification_service.py         # SES email + Telegram (token from Secrets Manager)
    utils/
      config.py                        # flat module of constants (IBKR URL, symbol, AWS, Massive.com key, Telegram/SES)
      decorators.py                    # generic retry(max_attempts, delay, backoff, no_retry_exceptions)
compose.yaml                           # ibeam (IB Gateway) + trader-bot sharing its network namespace
ibeam/                                 # IBeam credentials/config (env.list has real IBKR login, gitignored)
README.md                              # IBKR-based docs (already stale vs. code in a few places)
```

**Execution flow:** `execute-trade.py` → `Trader.execute_trade()`:
1. `IBKRClient.initialize()` — checks IBeam-authenticated session, suppresses IBKR's order-confirmation prompts.
2. `account_id = client.get_account_id()` — first account in `/iserver/accounts` (no selection logic — whatever the gateway session is authenticated as).
3. `strategy.get_signal(account_id)` — pure pandas signal off S3-cached QQQ OHLCV (backfilled from Massive.com), returns `Signal.BULLISH/BEARISH/CLOSED`. `account_id` here is only used to namespace the S3 bucket and notification labels — it plays no role in the signal math itself.
4. `client.get_contract_id(SYMBOL)`, `get_price`, `get_position`, `get_available_cash`, `get_account_balance`, `get_performance` — all IBKR REST calls, keyed by IBKR's numeric `conid`.
5. Bullish → `_handle_bullish_signal`: `amount = available_cash - ibkr_commission_estimate - $1 buffer`; `place_buy_order(account_id, conid, amount)` (IBKR cash-quantity market buy).
6. Bearish → `_handle_bearish_signal`: sells 100% of `current_position` via `place_sell_order` (share-quantity market sell).
7. `TradeLogger.log_trade` appends the trade to a per-account Excel workbook in S3 and fires a notification. No polling of order status anywhere — both handlers log the *requested* amount/order id immediately after submission.

**IBKR specifics that go away entirely:** the `ibeam` Docker sidecar and its network-namespace sharing trick, the conid lookup, IBKR's two-step order confirm (`/iserver/reply/{id}`), the order-reply message-suppression list, `VERIFY_SSL=False` self-signed-cert handling, and the IBKR TIERED/FIXED commission-estimation math baked into `trader.py`.

**Config/scheduling:** all settings are hardcoded Python constants in `utils/config.py` (no `.env`, no YAML/JSON config, no CLI args). No CI, no tests, no IaC exist in the repo. Scheduling is external (an example cron line in the README runs `docker-compose run --rm trader-bot` once daily) — nothing in-repo.

---

## B. Proposed Architecture

```
trader-bot/
  execute-trade.py                     # unchanged shape: Trader().execute_trade()
  requirements.txt                     # +alpaca-py, +PyYAML; -urllib3 (no longer needed explicitly)
  Dockerfile                           # unchanged
  accounts.yaml                        # NEW — data-driven multi-account config (see §F)
  .env.example                         # NEW — documents required per-account credential env vars
  algo_trader/
    core/
      strategy.py                      # UNCHANGED (signal logic untouched, per the migration brief)
      portfolio.py                     # NEW — broker-agnostic allocation math: cash + %s → per-ticker order plan
      trader.py                        # REWRITTEN — thin orchestrator: get signal once, loop enabled accounts,
                                        #   delegate sizing to portfolio.py, delegate execution to AlpacaClient
    clients/
      alpaca_client.py                 # NEW — replaces ibkr_client.py; wraps alpaca-py TradingClient
      ibkr_client.py                   # DELETED
    config/
      account_config.py                # NEW — AccountConfig dataclass + accounts.yaml loader/validator
    models/
      enums.py                         # unchanged
      trade.py                         # unchanged (already broker-agnostic)
    logging/                           # unchanged (cloudwatch_logger.py, trade_logger.py — keyed by account *name* now)
    notifications/                     # unchanged
    utils/
      config.py                        # TRIMMED — drop IBKR (BASE_URL/VERIFY_SSL) + single SYMBOL/COMMISSION_TYPE;
                                        #   keep AWS/S3/CloudWatch/SES/Telegram/Massive settings
      decorators.py                    # unchanged, reused by alpaca_client.py
  tests/                                # NEW — pytest unit tests (see §J)
compose.yaml                           # REWRITTEN — single trader-bot service, no ibeam, no shared network namespace
ibeam/                                 # DELETED entirely
README.md                              # REWRITTEN for Alpaca
```

This keeps the existing module layout almost entirely intact — the only structural addition is `core/portfolio.py` (the allocation layer the brief explicitly asks for) and `config/account_config.py` (multi-account config loading). No new abstraction layers, no broker-interface/plugin system, since there's only ever going to be one broker implementation in play at a time — that would be over-engineering for this codebase's size.

**New data flow:**
```
Strategy (unchanged)
    ↓ Signal (computed ONCE per run — see note below)
Trader (orchestrator)
    ↓ for each enabled AccountConfig
Portfolio (cash + allocation % → per-ticker dollar amounts, or "sell all" plan)
    ↓
AlpacaClient (submit orders, poll fill, on that account's own API key/secret)
    ↓
TradeLogger / NotificationService (per-account S3 bucket / log group / message, keyed by account name)
```

**Important behavioral change flagged for your awareness:** today, `strategy.get_signal(account_id)` is called once per account and namespaces its S3 cache (`qqq-price-history.csv`) and notifications by whatever `account_id` is passed in — but the signal math itself (QQQ-based) is identical regardless of account. With multiple accounts this would mean redundant Massive.com calls and duplicate S3 writes per account for the *same* market signal. The plan is to compute the signal **once per run**, using a single shared, account-independent S3 location for the QQQ cache, and pass the resulting `Signal` into the per-account loop. Per-account notification labeling is preserved (each account still gets its own "Market Signal: BULLISH" message). This is a straightforward simplification in service of the brief's "clean separation" requirement, not a change to the strategy's decision logic itself.

---

## C. Files to Modify

| File | Why |
|---|---|
| `trader-bot/algo_trader/core/trader.py` | Rewrite as orchestrator: drop IBKR imports/commission math, compute signal once, loop over enabled `AccountConfig`s, delegate sizing to `portfolio.py` and execution to `AlpacaClient` |
| `trader-bot/algo_trader/core/strategy.py` | Decouple from `account_id` — compute against one shared S3 key/bucket instead of an account-scoped one; keep all indicator/signal math byte-for-byte identical |
| `trader-bot/algo_trader/utils/config.py` | Remove `BASE_URL`, `VERIFY_SSL`, `SYMBOL`, `COMMISSION_TYPE` (superseded by `accounts.yaml`); keep AWS/S3/CloudWatch/SES/Telegram/Massive settings |
| `trader-bot/algo_trader/clients/__init__.py` | Export `AlpacaClient`/`OrderRejectionError` instead of `IBKRClient` |
| `trader-bot/algo_trader/logging/trade_logger.py` | Key S3 bucket/filename by account **name** (config key) instead of raw broker account id (Alpaca IDs are opaque UUIDs, not human-readable like IBKR's) |
| `trader-bot/algo_trader/logging/cloudwatch_logger.py` | Key log group by account name for the same reason |
| `trader-bot/algo_trader/notifications/notification_service.py` | Label messages with account name instead of raw account id |
| `trader-bot/execute-trade.py` | Update docstring (IBKR → Alpaca); logic unchanged |
| `trader-bot/requirements.txt` | Add `alpaca-py`, `PyYAML`; drop `urllib3` (was only needed to silence IBKR's self-signed-cert warning) |
| `compose.yaml` | Remove the `ibeam` service and `network_mode: "service:ibeam"`; `trader-bot` becomes a standalone service (no gateway dependency) |
| `README.md` | Full rewrite for Alpaca (see §9 of the brief) |
| `.gitignore` | Add `.env` / `accounts.local.yaml` patterns if we split secrets from the checked-in `accounts.yaml` (see §F) |

## D. Files to Delete

| File/Dir | Why |
|---|---|
| `trader-bot/algo_trader/clients/ibkr_client.py` | Entirely IBKR Client Portal Web API-specific; replaced by `alpaca_client.py` |
| `ibeam/` (`env.list`, `README.md`) | IB Gateway/IBeam sidecar scaffolding has no Alpaca equivalent — Alpaca's REST/SDK API needs no local gateway process. `env.list` also contains a real (if now-to-be-revoked) IBKR credential checked into git — flagging that those IBKR credentials should be rotated/revoked at IBKR after cutover, independent of deleting the file, since git history retains them. |

I did not find any other file that's safe to delete outright — everything else (`strategy.py`, models, logging, notifications, `decorators.py`) is already broker-independent and is being kept.

## E. Files to Add

| File | Purpose |
|---|---|
| `trader-bot/algo_trader/clients/alpaca_client.py` | Thin `AlpacaClient` wrapping `alpaca-py`'s `TradingClient`/`StockHistoricalDataClient` for one account's credentials — mirrors the current `IBKRClient` method surface where practical (see §H) |
| `trader-bot/algo_trader/core/portfolio.py` | Broker-agnostic allocation logic: given available cash + an `AccountConfig`'s ticker percentages → list of `(symbol, notional_amount)` buy orders; given "sell all" → list of symbols to liquidate. Pure functions, easy to unit test without hitting any API. |
| `trader-bot/algo_trader/config/account_config.py` | `AccountConfig` dataclass (`name`, `api_key_env`, `api_secret_env`, `paper`, `enabled`, `allocations: dict[str, float]`) + loader/validator for `accounts.yaml` (fails fast if a given account's percentages don't sum to ~100%, or if referenced env vars are missing) |
| `trader-bot/accounts.yaml` | The data-driven multi-account/ticker-allocation config (see §F) |
| `trader-bot/.env.example` | Documents the `ALPACA_API_KEY_<NAME>` / `ALPACA_API_SECRET_<NAME>` env vars each account config expects |
| `trader-bot/tests/` | New pytest suite (see §J) — `test_portfolio.py`, `test_account_config.py`, `test_trader.py` (mocked `AlpacaClient`) |

---

## F. Configuration Changes

**`accounts.yaml`** (checked into git — no secrets, just structure):
```yaml
accounts:
  - name: taxable
    enabled: true
    paper: true
    api_key_env: ALPACA_API_KEY_TAXABLE
    api_secret_env: ALPACA_API_SECRET_TAXABLE
    allocations:
      TQQQ: 100

  - name: roth-ira
    enabled: true
    paper: true
    api_key_env: ALPACA_API_KEY_ROTH_IRA
    api_secret_env: ALPACA_API_SECRET_ROTH_IRA
    allocations:
      VTI: 20
      VOO: 20
      VUG: 30
      VGT: 15
      QQQ: 15
```
- Adding/removing an account or changing allocations is a YAML edit only — no code changes, satisfying the brief's "data-driven" requirement.
- `account_config.py` validates on load: each account's `allocations` must sum to 100% (± a small epsilon), `api_key_env`/`api_secret_env` must resolve to non-empty environment variables for any `enabled: true` account, and account `name`s must be unique (they're used as the S3/log-group/notification key).
- Actual secrets (`ALPACA_API_KEY_*` / `ALPACA_API_SECRET_*`) come from environment variables — locally via a `.env` file (gitignored, `.env.example` documents the expected names) or `docker-compose`'s `environment`/`env_file`; on AWS, the same env var names would be populated from Secrets Manager/Parameter Store at deploy time. This mirrors the existing pattern already used for the Telegram bot token.
- `paper: true/false` per account maps directly to `alpaca.trading.client.TradingClient(api_key, secret_key, paper=...)` — no more manually-swapped base URLs.

## G. Trading Flow

```
execute-trade.py
    ↓
Trader.execute_trade()
    ↓
strategy.get_signal()                          # ONE call per run, broker/account-independent
    ↓
load accounts.yaml → [AccountConfig, ...]        # filter to enabled=true
    ↓  (for each account, independently)
AlpacaClient(account)                            # built from that account's own key/secret + paper flag
    ↓
get_account() → cash                              get_all_positions() → current holdings
    ↓                                                       ↓
portfolio.plan_buy(cash, account.allocations)      portfolio.plan_sell_all(positions)
    ↓                                                       ↓
[(symbol, notional_amount), ...]                    [symbol, ...]  (every open position, per your "sell scope" answer)
    ↓                                                       ↓
AlpacaClient.submit_notional_buy(symbol, amount)    AlpacaClient.close_position(symbol)
    ↓                                                       ↓
poll order status until terminal (filled/rejected/canceled), bounded timeout
    ↓
Trade(account_id=account.name, ...) → TradeLogger.log_trade()  → S3 Excel + notification
```
On `Signal.CLOSED`, no account loop runs (matches today's no-op). Each account is processed independently — a failure/rejection in one account is caught, logged, and notified without aborting the other accounts' runs (today's single-account `try/except` around the whole run becomes a per-account `try/except` inside the loop, with one outer summary catch for signal-generation failures that would abort the whole run since no account can trade without a signal).

## H. Alpaca API Mapping

| Current IBKR functionality | Alpaca equivalent |
|---|---|
| Auth via IBeam-managed session cookie (`localhost:5000`, self-signed cert) | `APCA-API-KEY-ID` / `APCA-API-SECRET-KEY` headers — `alpaca.trading.client.TradingClient(key, secret, paper=...)`. No gateway process, no cookie/session state, real TLS. |
| `get_account_id()` → first of `/iserver/accounts` | Not needed the same way — each Alpaca account **is** a separate key/secret pair (see Risk below); `TradingClient.get_account().id` if the UUID is needed for logging, but we key everything by the config `name` instead |
| `get_available_cash` → `availableFunds` | `TradingClient.get_account().buying_power` (closest behavioral analog to IBKR's margin-inclusive available funds; effectively equals `cash` for non-marginable accounts like IRAs) |
| `get_account_balance` → `netLiquidationValue` | `TradingClient.get_account().equity` |
| `get_contract_id(symbol)` → IBKR `conid` | **No equivalent needed** — Alpaca addresses everything by ticker symbol directly; this method is simply dropped |
| `get_price(conid)` → last daily close | `StockHistoricalDataClient.get_stock_latest_trade(symbol)` (or latest bar) — used only for logging/estimated-shares display, not for order sizing (notional orders don't need a price) |
| `get_position(account_id, conid)` | `TradingClient.get_all_positions()` fetched once per account, looked up by symbol locally (fewer API calls than one lookup per ticker); absence = no position (Alpaca 404s on `get_open_position` for an unheld symbol) |
| `place_buy_order(..., cash_quantity)` (IBKR `cashQty` market buy) | `TradingClient.submit_order(MarketOrderRequest(symbol=..., notional=amount, side=BUY, time_in_force=DAY))` — direct match, dollar-denominated, fractional-share-capable |
| `place_sell_order(..., quantity)` (share-based market sell) | `TradingClient.close_position(symbol)` — liquidates the entire position in one call (handles fractional qty automatically), simpler than IBKR's manual qty calc |
| `_confirm_order` (IBKR's two-step order-reply confirmation) | **No equivalent** — Alpaca orders are accepted/rejected synchronously on submission; dropped entirely, along with the `suppress_message_ids` IBKR-question-suppression list |
| No order-status polling today | `TradingClient.get_order_by_id(order_id)` polled with backoff until a terminal status (`filled`/`canceled`/`rejected`/`expired`) or timeout — new capability per your "poll until filled" answer |
| `OrderRejectionError` (parsed from IBKR's `cqe.post_payload.rejections`) | Alpaca SDK raises `alpaca.common.exceptions.APIError` on rejection; wrap/translate into the same `OrderRejectionError` type so `trader.py`'s exception handling is unchanged |
| `get_performance()` → IBKR `/pa/performance` NAV history + buy-and-hold SPY/QQQ overlay via IBKR market-data history | `TradingClient.get_portfolio_history()` (`GET /v2/account/portfolio/history`, fields `timestamp`/`equity`/`profit_loss_pct`) for the account curve; `StockHistoricalDataClient.get_stock_bars()` for the SPY/QQQ buy-and-hold overlay. Chart/Telegram-caption logic is otherwise reused as-is. The one-off `if account_id == "U20831848": cutoff = ...` NAV-filtering hack is dropped (it was tied to a specific IBKR account number and has no Alpaca equivalent; flagged in Risks) |
| IBKR TIERED/FIXED commission estimation (`_get_ibkr_commission`) | **Removed entirely** — Alpaca's standard equities trading is commission-free, so there's nothing to estimate/subtract before sizing a buy |
| IBKR API rate limits (undocumented in-repo; handled only via generic retry/backoff) | Alpaca's standard (non-Broker) Trading API is a per-key-pair limit (documented at `docs.alpaca.markets/docs/rate-limit` — worth a quick confirmation at implementation time); since each account uses its own key pair, one account's activity can't exhaust another's limit. The existing `retry()` decorator (3 attempts, 2s/4s backoff) is reused unchanged for `AlpacaClient` |
| Paper vs. live via manually swapping `BASE_URL` | `TradingClient(..., paper=True/False)` — one boolean per account in `accounts.yaml`, defaulting to `paper: true` |
| Market hours check | `strategy.py` already gates on the NYSE calendar via `pandas_market_calendars` before any account is touched — kept as-is; `TradingClient.get_clock()` could optionally be added as a defensive pre-order sanity check but isn't required to replicate current behavior |

## I. Dependencies

- **Remove:** `urllib3` — was pinned only to call `urllib3.disable_warnings(...)` around IBKR's self-signed cert; Alpaca uses real TLS so this goes away (still present transitively via `requests`/`boto3`, just no longer an explicit/direct dependency or import).
- **Add:** `alpaca-py` (official Alpaca Python SDK — trading + market data clients), `PyYAML` (parse `accounts.yaml`).
- **Unchanged:** `requests` (Massive.com calls in `strategy.py`, Telegram calls), `pandas`, `boto3`, `pandas_market_calendars`, `matplotlib`, `openpyxl`.

## J. Testing Plan

No test infrastructure exists today (README references a `tests/` dir and pytest that were never actually created). Proposed additions, all new:

- **`portfolio.py` unit tests** (pure functions, no mocking needed): given cash + allocation % → correct per-ticker notional amounts; rounding/remainder handling; behavior when computed per-ticker amount is below Alpaca's minimum order size (skip that ticker, still process the rest); "sell all" plan includes every held symbol regardless of whether it's in the account's `allocations`.
- **`account_config.py` unit tests**: valid config loads correctly; percentages not summing to 100% raises a clear validation error; missing env var for an enabled account raises; disabled accounts are excluded from the run.
- **`trader.py` orchestration tests** with a mocked `AlpacaClient`: bullish signal → correct calls into the mocked client per enabled account; bearish signal → `close_position` called for every held symbol; a rejection/exception in one account's processing doesn't stop the other accounts from running; `Signal.CLOSED` → no account touched.
- **Insufficient-cash and API-error handling**: cash below threshold logs a warning and skips the buy without raising; a simulated `APIError`/rejection is translated into `OrderRejectionError`, caught, logged, and notified (mirrors current behavior).
- **Strategy regression check** (manual, one-time): run `strategy.py` before and after decoupling it from `account_id`/switching its S3 key to the shared location, against the same cached price history, and confirm the emitted `Signal` and computed indicator columns are identical — this is the strongest guarantee that "the strategy is unchanged" holds.
- **Paper-trading end-to-end verification** (manual): with `paper: true` accounts configured against real Alpaca paper endpoints, run a full cycle and confirm buy orders land at the expected notional amounts, sell orders liquidate full positions, and trade logs/notifications reflect actual fill data from polling.

## K. Risks / Decisions Needed

- **Alpaca account provisioning**: this plan assumes you already have (or will have) separate Alpaca brokerage accounts opened for each entry you want in `accounts.yaml`, each with its own API key/secret pair — Alpaca's standard (non-Broker) Trading API has no concept of "sub-accounts under one login"; every account, including each IRA type, needs its own credential pair. Please confirm which accounts currently exist / are ready before implementation, and provide their names/labels for `accounts.yaml`.
- **`buying_power` vs `cash` for available funds**: I'm defaulting to Alpaca's `buying_power` field (closest behavioral match to IBKR's margin-inclusive `availableFunds`), which is effectively equal to `cash` on non-marginable accounts like IRAs. Flagging in case you'd prefer strictly `cash` everywhere regardless of account type (e.g. to intentionally avoid margin exposure even where a taxable account could support it).
- **Pre-existing secret-hygiene issues, out of migration scope but worth a decision**: `utils/config.py` has a plaintext `MASSIVE_API_KEY` checked into git, and `ibeam/env.list` (to be deleted) contains what looks like a real IBKR credential in git history. Since we're already touching `config.py`, want me to move `MASSIVE_API_KEY` to an env var/Secrets Manager as part of this change, or leave it as-is for a separate cleanup?
- **IBKR account-specific NAV hack**: the `if account_id == "U20831848"` cutoff filter in `get_performance()` is dropped entirely (no Alpaca equivalent, tied to a specific IBKR account). If any Alpaca account's portfolio-history chart needs a similar "ignore data before date X" filter after cutover, that'll need to be re-added per-account in `accounts.yaml` rather than hardcoded — flagging so it isn't silently lost.
- **Rate limits**: I've described Alpaca's per-key-pair rate limiting at a high level but couldn't pull exact numeric limits from the docs during this review (the fetched page only covered Broker-API correspondent-level limits); worth a quick confirmation against `docs.alpaca.markets/docs/rate-limit` at implementation time, though it shouldn't materially affect design since each account is already isolated by its own key.

---

Once this plan is approved, implementation will proceed step-by-step (broker client → portfolio layer → account config/loader → trader rewrite → compose/README/dependency cleanup → tests), with nothing deleted until its replacement is in place and working.
