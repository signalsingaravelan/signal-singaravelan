# Trading Bot

A Python trading bot that integrates with Interactive Brokers Web API to execute automated trades based on market signals.

## Project Structure

```
├── main.py              # Entry point
├── trading_bot.py       # Main trading bot orchestration
├── ibkr_client.py       # Interactive Brokers API client with market data
├── strategy.py          # Trading strategy implementation
├── utils.py             # Utility functions and decorators
├── config.py            # Configuration settings
├── requirements.txt     # Python dependencies
└── README.md           # This file
```

## Installation

1. **Clone or download the project files**

2. **Run the trading bot:**
   ```bash
   python main.py
   ```
   
   The script will automatically check for and install any missing dependencies on first run.

**Alternative manual installation:**
If you prefer to install dependencies manually:
```bash
pip install -r requirements.txt
python main.py
```

3. **Configure Interactive Brokers:**
   - Ensure IBKR Gateway or TWS is running
   - Enable API connections in your IBKR settings
   - Update `config.py` if needed for your specific setup

## Usage

Run the trading bot:

```bash
python main.py
```

The bot will:
1. **Auto-install dependencies** if any are missing
2. Authenticate with IBKR Web API
3. Get your account information
4. Analyze market conditions using the configured strategy
5. Execute trades based on the generated signals

## Configuration

Edit `config.py` to customize:

- **API Settings**: Base URL and SSL verification
- **Trading Parameters**: Position sizes and contract IDs
- **Retry Logic**: Attempt counts and delays

## Error Handling

The bot includes comprehensive error handling:
- Automatic retries for transient failures
- Graceful degradation when services are unavailable
- Detailed logging of all operations and errors

## Dependencies

- `requests`: HTTP client for API communication
- `yfinance`: Yahoo Finance data provider
- `urllib3`: HTTP library (used to disable SSL warnings)
- `ibind`: Simplified Interactive Brokers Web API client

## License

This project is for educational and personal use. Please ensure compliance with your broker's terms of service and applicable financial regulations.