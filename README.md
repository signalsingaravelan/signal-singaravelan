# Signal Singaravelan — Alpaca Trading Bot

An automated trading system that runs a NASDAQ-100 technical-analysis strategy (IBD Follow-Through-Day / "Black Dot" / "Red Dot" signals on QQQ) once per invocation and, on a bullish or bearish signal, trades a configurable set of tickers across one or more independent [Alpaca](https://alpaca.markets) brokerage accounts.

## Architecture

```
execute-trade.py (entry point)
       ↓
   Trader (orchestrator)
       ↓
   strategy.get_signal()  ──────────► one Signal per run (BULLISH / BEARISH / CLOSED)
       ↓
   accounts.yaml  ──────► [AccountConfig, ...]  (only enabled accounts)
       ↓  for each account, independently
   portfolio.py  ──────► cash + allocation % → buy plan, or open positions → sell-all plan
       ↓
   AlpacaClient (that account's own API key/secret)
       ↓
   TradeLogger / NotificationService  ──────► S3 Excel log, email/Telegram, keyed by account name
```

- **Strategy** (`strategy.py`) is entirely broker- and account-independent: it decides BULLISH/BEARISH/CLOSED once per run from QQQ price/volume history, regardless of how many accounts are configured.
- **Portfolio** (`core/portfolio.py`) turns an account's available cash and its configured ticker percentages into a concrete buy plan (or turns its open positions into a sell-everything plan) — pure functions with no broker calls.
- **Broker execution** (`clients/alpaca_client.py`) is the only layer that talks to Alpaca. Swapping brokers in the future means replacing this one file/class.

## Project Structure

```
trader-bot/
├── execute-trade.py                 # Entry point
├── accounts.yaml                    # Multi-account / ticker-allocation configuration
├── .env.example                     # Documents required credential env vars
├── requirements.txt
├── Dockerfile
├── tests/                           # pytest unit tests
└── algo_trader/
    ├── core/
    │   ├── strategy.py              # Signal generation (NASDAQ-100 / IBD FTD)
    │   ├── portfolio.py             # Cash + allocation % → order plan
    │   └── trader.py                # Orchestrator: signal → per-account loop → broker
    ├── clients/
    │   └── alpaca_client.py         # Alpaca Trading + Market Data API wrapper
    ├── config/
    │   └── account_config.py        # accounts.yaml loader/validator
    ├── models/
    │   ├── enums.py                 # Signal, Severity
    │   └── trade.py                 # Trade record
    ├── logging/
    │   ├── cloudwatch_logger.py     # Console + CloudWatch logging
    │   └── trade_logger.py          # Trade history Excel workbook in S3
    ├── notifications/
    │   └── notification_service.py  # Email (SES) + Telegram alerts
    └── utils/
        ├── config.py                # Non-account settings (AWS, retry, thresholds)
        └── decorators.py            # Generic retry decorator
compose.yaml                         # Single-service Docker Compose config
```

## Prerequisites

- One or more [Alpaca](https://alpaca.markets) brokerage accounts, each with its own API key/secret pair (generated from the Alpaca dashboard — paper or live). Alpaca has no concept of sub-accounts under a single key; every account you want to trade needs its own credential pair.
- Python 3.11+ (if running locally) or Docker.
- An AWS account for S3 (trade logs, cached market data) and, optionally, CloudWatch/SES/Secrets Manager.

## Installation & Setup

### 1. Install dependencies

```bash
cd trader-bot
pip install -r requirements.txt
```

### 2. Configure accounts

Copy `.env.example` to `.env` and fill in the API key/secret for each account you enable in `accounts.yaml`:

```bash
cp .env.example .env
```

Edit `trader-bot/accounts.yaml` to define which accounts trade and how each one allocates its cash. Example:

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

- `enabled: false` excludes an account from a run without deleting its config.
- `paper: true/false` selects Alpaca's paper-trading or live-trading endpoint for that account. **New accounts should stay on `paper: true` until you've verified a few runs.**
- `allocations` must sum to 100 for any enabled account — the system validates this at startup and refuses to run otherwise.
- Adding, removing, or reallocating an account is a YAML edit only; no code changes required.

### 3. Configure AWS credentials

```bash
aws configure
# or
export AWS_ACCESS_KEY_ID=your_access_key
export AWS_SECRET_ACCESS_KEY=your_secret_key
export AWS_DEFAULT_REGION=us-east-1
```

### 4. Review non-account settings

`trader-bot/algo_trader/utils/config.py` holds settings that aren't per-account: S3 bucket/prefix, CloudWatch log group, SES from/to addresses, Telegram chat ID, Massive.com API key, and retry tuning.

## Usage

### Local

```bash
cd trader-bot
python execute-trade.py
```

### Docker

```bash
docker-compose build trader-bot
docker-compose run --rm trader-bot
```

### Scheduling

Nothing in this repo schedules runs automatically. Trigger `execute-trade.py` (or `docker-compose run --rm trader-bot`) however fits your environment — e.g. an external cron entry:

```bash
0 13 * * 1-5 cd /path/to/project && docker-compose run --rm trader-bot
```

## How a Run Works

1. `strategy.get_signal()` computes one `Signal` (`BULLISH`, `BEARISH`, or `CLOSED`) from QQQ price/volume history — cached in S3, backfilled from Massive.com when stale. On `CLOSED` (non-trading day), no account is touched.
2. For every account with `enabled: true` in `accounts.yaml`, independently:
   - **Bullish**: fetch that account's buying power, split it across its configured tickers per their percentages (skipping any ticker whose share falls below Alpaca's minimum notional order size), and submit a dollar-denominated market buy for each.
   - **Bearish**: liquidate every open position in the account, regardless of whether it's part of the configured allocation — the goal is 100% cash.
   - Orders are submitted and logged immediately without waiting for a fill — the system is designed to run before market open, so day market orders simply queue until the exchange opens. The logged share count (buys) or dollar amount (sells) is an estimate from the latest quote, not the confirmed fill; check Alpaca's dashboard/order history for actual execution price and time.
3. A failure or order rejection in one account is logged and notified without stopping the other accounts from processing.

## Paper vs. Live Trading

Each account's `paper` flag in `accounts.yaml` controls this independently — you can run some accounts on paper and others live in the same deployment. `TradingClient(..., paper=True)` routes to Alpaca's paper-trading environment automatically; no separate credentials or URLs to manage beyond the account's own API key/secret (Alpaca paper and live accounts use different key pairs).

## Environment Variables / Secrets

| Variable | Purpose |
|---|---|
| `ALPACA_API_KEY_<NAME>` / `ALPACA_API_SECRET_<NAME>` | One pair per account in `accounts.yaml`, matching its `api_key_env`/`api_secret_env` |
| AWS credentials (via `aws configure`, env vars, or an IAM role) | S3 (trade logs, market data cache), CloudWatch, SES, Secrets Manager |
| `TELEGRAM_CHAT_ID` (optional) | Overrides the default configured in `config.py` |

The Telegram bot token is read from AWS Secrets Manager (`SignalSingaravelanSecrets`, key `TelegramBotToken`), not an environment variable.

## Testing

```bash
cd trader-bot
pip install pytest
python -m pytest tests/
```

The suite covers allocation math (`portfolio.py`), `accounts.yaml` loading/validation, and the trading orchestration logic (`trader.py`) with the Alpaca client mocked — no network or credentials required to run it. Strategy logic (`strategy.py`) isn't covered by automated tests; verify signal changes manually against known historical data.

## AWS Deployment

Deployment target is AWS; no infrastructure-as-code exists in this repo yet. Current AWS integrations (all via `boto3`, created lazily at runtime — no separate provisioning step):

- **S3**: cached QQQ price history, market-outlook analysis workbook, and per-account trade-history Excel logs (bucket names derived from `S3_BUCKET_NAME` in `config.py`).
- **CloudWatch Logs**: per-account log groups (falls back to console-only logging if credentials/CloudWatch are unavailable).
- **SES**: trade/error email notifications.
- **Secrets Manager**: Telegram bot token.

Whatever compute environment runs `execute-trade.py` (EC2, ECS, Lambda, etc.) needs IAM permissions for these services and the account-specific `ALPACA_API_KEY_*`/`ALPACA_API_SECRET_*` env vars populated (e.g. from Secrets Manager/Parameter Store at deploy time).

## Disclaimer

This software is for educational and research purposes only. Trading involves substantial risk of loss and is not suitable for all investors. Always test thoroughly with paper trading before using real money. The authors are not responsible for any financial losses. Use at your own risk and ensure compliance with all applicable regulations.
