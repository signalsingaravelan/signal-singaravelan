# Automated Trading Bot - NASDAQ 100 Index Monitor

A sophisticated Python-based automated trading system that implements the "NASDAQ 100 Index Monitor" strategy for Interactive Brokers. The system uses technical analysis to generate trading signals and automatically executes trades on TQQQ (ProShares UltraPro QQQ ETF).

## 🏗️ System Architecture

The trading bot consists of four core components working together:

```
execute-trade.py (Entry Point)
       ↓
   trader.py (Orchestrator)
       ↓
   ┌─────────────────┬─────────────────┐
   ↓                 ↓                 ↓
strategy.py      ibkr_client.py    AWS Services
(Signal Gen)     (Broker API)      (S3, CloudWatch, SES)
```

## 📁 Project Structure

```
├── ibeam/                          # IBeam configuration
│   ├── env.list                    # IBKR credentials (create this file)
│   └── README.md                   # IBeam setup instructions
├── trader-bot/                     # Main trading application
│   ├── algo_trader/                # Core trading package
│   │   ├── clients/                # External service clients
│   │   │   └── ibkr_client.py      # Interactive Brokers API client
│   │   ├── core/                   # Core trading logic
│   │   │   ├── strategy.py         # NASDAQ 100 Index Monitor strategy
│   │   │   └── trader.py           # Main trading orchestrator
│   │   ├── logging/                # Logging infrastructure
│   │   │   ├── cloudwatch_logger.py
│   │   │   └── trade_logger.py
│   │   ├── models/                 # Data models
│   │   │   ├── enums.py           # Signal and severity enums
│   │   │   └── trade.py           # Trade data model
│   │   ├── notifications/          # Notification services
│   │   │   └── notification_service.py
│   │   └── utils/                  # Utilities
│   │       ├── config.py          # Configuration settings
│   │       └── decorators.py      # Retry decorator
│   ├── execute-trade.py           # Application entry point
│   ├── Dockerfile                 # Container configuration
│   └── requirements.txt           # Python dependencies
├── compose.yaml                   # Docker Compose configuration
└── README.md                      # This file
```

## 🎯 Trading Strategy: NASDAQ 100 Index Monitor

The system implements a sophisticated technical analysis strategy based on market volatility and volume indicators:

### Signal Types
- **🟢 BULLISH**: No warning signals in past 10 trading days → BUY
- **🔴 BEARISH**: Warning signal present today → SELL immediately  
- **🟡 NEUTRAL**: Warning signal in past 10 days but not today → SELL
- **⚫ CLOSED**: Market closed → No action

### Technical Indicators

#### Black Dot ⚫ (Sudden Heavy Selling)
Indicates short-term bearish risk (similar to 2020 COVID crash):
- Today's close < 50-day moving average
- All conditions met on same day within past 5 trading days:
  - True Range > 1.5 × Average True Range (volatility spike)
  - Closing Range < 10% (closes near daily low)
  - Volume > 50-day moving average (high selling pressure)

#### Red Dot 🔴 (Ongoing Weakness)  
Indicates medium-term bearish risk (similar to 2022 bear market):
- Today's close < 50-day moving average
- Up/Down Volume Ratio < 1 for 3+ times in past 5 trading days

## 🚀 Features

### Core Functionality
- **Automated Signal Generation**: Downloads NDX data and calculates technical indicators
- **Smart Order Execution**: Handles both cash-based buying and share-based selling
- **Risk Management**: Built-in cash buffers and position validation
- **Fractional Share Support**: Supports fractional share trading
- **Order Rejection Handling**: Comprehensive error handling for failed orders

### AWS Cloud Integration
- **S3 Storage**: Automatic upload of trade logs and market analysis
- **CloudWatch Logging**: Account-specific log groups with detailed execution logs
- **SES Notifications**: Email alerts for trade execution and errors
- **Secrets Manager**: Secure storage of sensitive credentials

### Monitoring & Reporting
- **Excel Reports**: Detailed market analysis with all technical indicators
- **Trade Logging**: Complete audit trail of all trading activities
- **Real-time Notifications**: Telegram and email alerts
- **Error Tracking**: Comprehensive error logging and alerting

## 📋 Prerequisites

- **Interactive Brokers Account**: Active trading account with API access
- **Docker & Docker Compose**: For containerized deployment
- **AWS Account**: For cloud services (S3, CloudWatch, SES)
- **Python 3.11+**: If running locally

## 🛠️ Installation & Setup

### 1. Clone Repository
```bash
git clone <repository-url>
cd trading-bot
```

### 2. Configure IBKR Credentials
Create `ibeam/env.list` with your Interactive Brokers credentials:
```bash
IBEAM_ACCOUNT=your_account_id
IBEAM_PASSWORD=your_password
```

### 3. Configure AWS Credentials
Ensure AWS credentials are available:
```bash
# Option 1: AWS CLI configured
aws configure

# Option 2: Environment variables
export AWS_ACCESS_KEY_ID=your_access_key
export AWS_SECRET_ACCESS_KEY=your_secret_key
export AWS_DEFAULT_REGION=us-east-1
```

### 4. Update Configuration
Edit `trader-bot/algo_trader/utils/config.py` with your settings:
- S3 bucket names
- Email addresses for notifications
- Telegram chat IDs
- CloudWatch log groups

## 🚀 Usage

### Local Development
```bash
# Start IBeam gateway
docker-compose up -d ibeam

# Run trading bot once
docker-compose run --rm trader-bot

# View logs
docker-compose logs ibeam
docker-compose logs trader-bot
```

### Production Deployment
```bash
# Build and run
docker-compose up -d ibeam
docker-compose run --rm trader-bot

# Schedule daily execution (example cron)
0 13 * * 1-5 cd /path/to/project && docker-compose run --rm trader-bot
```

## 📊 Monitoring & Logs

### CloudWatch Integration
- Account-specific log groups: `/aws/ecs/trader-bot-{account_id}`
- Structured logging with timestamps and severity levels
- Error tracking and alerting

### S3 Storage
- **Trade Logs**: `s3://signal-singaravelan-{account_id}/trade-history/`
- **Market Data**: `s3://signal-singaravelan-{account_id}/trade-history/ndx-price-history.csv`
- **Analysis Reports**: `s3://signal-singaravelan-{account_id}/trade-history/market-outlook.xlsx`

### Notifications
- **Email**: Trade confirmations and error alerts via AWS SES
- **Telegram**: Real-time notifications via bot integration

## 🔧 Configuration

### Key Configuration Files
- `trader-bot/algo_trader/utils/config.py`: Main configuration
- `ibeam/env.list`: IBKR credentials
- `compose.yaml`: Docker services configuration

### Customizable Parameters
- **Trading Symbol**: Currently set to TQQQ
- **Commission Structure**: TIERED or FIXED
- **Cash Thresholds**: Minimum cash and buffer amounts
- **Technical Indicators**: Lookback periods and thresholds

## 🧪 Testing

### Paper Trading
Always test with IBKR paper trading account before live deployment:
1. Set up paper trading account in IBKR
2. Update credentials in `ibeam/env.list`
3. Run system in paper trading mode
4. Verify all functionality works correctly

### Local Testing
```bash
# Test individual components
python -m pytest tests/

# Test strategy signals
python -c "from algo_trader.core.strategy import TradingStrategy; s = TradingStrategy(); print(s.get_signal('TEST'))"

# Test IBKR connection
docker-compose up -d ibeam
# Wait for authentication, then test API calls
```

## 📈 Performance & Risk Management

### Built-in Risk Controls
- **Minimum Cash Threshold**: $5 minimum before placing trades
- **Cash Buffer**: $1 buffer to prevent overdraft
- **Position Validation**: Checks existing positions before selling
- **Order Rejection Handling**: Graceful handling of broker rejections
- **Market Calendar**: Only trades on valid trading days

### Commission Management
- **TIERED**: $0.0035/share, min $0.35, max 1% of trade value
- **FIXED**: $0.005/share, min $1.00
- Automatic commission calculation and deduction

## 🔍 Troubleshooting

### Common Issues
1. **Authentication Failures**: Check IBKR credentials and account status
2. **Order Rejections**: Verify account has sufficient funds and permissions
3. **Market Data Issues**: Ensure market is open and symbol is valid
4. **AWS Permissions**: Verify IAM roles have required permissions

### Debug Mode
Enable detailed logging by setting log level to DEBUG in configuration.

## 📄 Dependencies

### Core Python Packages
- `requests==2.32.5`: HTTP client for IBKR API
- `pandas==3.0.0`: Data analysis and technical indicators
- `boto3==1.42.36`: AWS services integration
- `openpyxl==3.1.5`: Excel report generation
- `pandas_market_calendars==5.3.0`: Market calendar functionality

See `trader-bot/requirements.txt` for complete dependency list.

## ⚠️ Disclaimer

**IMPORTANT**: This software is for educational and research purposes only. 

- Trading involves substantial risk of loss and is not suitable for all investors
- Past performance does not guarantee future results
- Always test thoroughly with paper trading before using real money
- The authors are not responsible for any financial losses
- Use at your own risk and ensure compliance with all applicable regulations

## 📜 License

This project is provided as-is for educational purposes. Use at your own risk.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Submit a pull request

## 📞 Support

For issues and questions:
1. Check the troubleshooting section
2. Review CloudWatch logs for detailed error information
3. Verify all configuration settings
4. Test with paper trading account first