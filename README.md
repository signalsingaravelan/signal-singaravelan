# Signal Singaravelan (Trading Bot)

A Python-based trading client for Interactive Brokers with **IBKR Web API** - Direct REST API integration with IBeam gateway.

This application implements automated trading strategies for TQQQ (ProShares UltraPro QQQ ETF).

## Project Structure

```
├── ibeam                # Placeholder folder to add env.list file with environment variables
├── trader-bot           # Python scripts containig the trading bot
├── compose.yaml         # Docker Compose configuration for Ibeam & Trader-bot
└── README.md            # This file
```

## Prerequisites

- Python 3.8+
- Interactive Brokers account
- **For Web API**: Docker and Docker Compose

## Installation & Usage

1. **Clone the repository and navigate to the project directory**

2. **Create a env.list file under IBeam folder with IBKR Credentials**

3. **Start IBeam server, which acts as a gateway between your application and Interactive Brokers**
   ```bash
   docker build 
   docker-compose up -d ibeam
   ```

4. **One time execution of trading bot:**
   ```bash
   docker build #Needs to run everytime a script change is made
   docker-compose run --rm trader-bot
   ```

For every execution the bot will:
1. Authenticate with IBKR
2. Retrieve account information
3. Get the current market signal
4. Execute trades based on the strategy

## Strategy Customization

The trading strategy is implemented in `strategy.py`. Currently, it returns a simple bullish signal. This needs to be modified. 

## Disclaimer

This software is for educational and research purposes only. Trading involves substantial risk of loss and is not suitable for all investors. Past performance does not guarantee future results. Always test thoroughly with paper trading before using real money.

## License

This project is provided as-is for educational purposes. Use at your own risk.