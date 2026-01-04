# IBKR Trading Client

A Python-based trading client for Interactive Brokers with **IBKR Web API** - Direct REST API integration with IBeam gateway.

This application implements automated trading strategies for TQQQ (ProShares UltraPro QQQ ETF).

## Project Structure

```
├── main.py              # Entry point (Web API version)
├── trader.py            # Main trading orchestration (Web API)
├── ibkr_client.py       # IBKR Web API client
├── strategy.py          # Trading strategy implementation
├── config.py            # Configuration settings
├── utils.py             # Utility functions and decorators
├── requirements.txt     # Python dependencies
├── compose.yaml         # Docker Compose configuration
├── env.list             # Environment variables
└── README.md            # This file
```

## Prerequisites

- Python 3.8+
- Interactive Brokers account
- **For Web API**: Docker and Docker Compose

## Installation

1. **Clone the repository and navigate to the project directory**

2. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Choose your implementation:**

3a. **Configure your IBKR credentials:**
   
   Edit the `env.list` file with your IBKR credentials:
   ```
   IBEAM_ACCOUNT=your_ibkr_username
   IBEAM_PASSWORD=your_ibkr_password
   ```

3b. **Start the IBeam gateway:**
   ```bash
   docker-compose up -d
   ```

## Usage

### Web API Version
```bash
python main.py
```

Both implementations will:
1. Authenticate with IBKR
2. Retrieve account information
3. Get the current market signal
4. Execute trades based on the strategy

## Strategy Customization

The trading strategy is implemented in `strategy.py`. Currently, it returns a simple bullish signal. This needs to be modified. 

## Docker Setup

The included `compose.yaml` configures IBeam, which acts as a gateway between your application and Interactive Brokers:

- **Port 5000**: IBKR Web API
- **Port 5001**: IBeam web interface
- **Network mode**: Bridge (required for IBKR IP whitelist)

## Troubleshooting

### Authentication Issues
- Ensure IBeam container is running: `docker-compose ps`
- Check IBeam logs: `docker-compose logs ibeam`
- Verify credentials in `env.list`

## Disclaimer

This software is for educational and research purposes only. Trading involves substantial risk of loss and is not suitable for all investors. Past performance does not guarantee future results. Always test thoroughly with paper trading before using real money.

## License

This project is provided as-is for educational purposes. Use at your own risk.