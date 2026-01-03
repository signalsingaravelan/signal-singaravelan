"""Configuration settings for the trading bot."""

# API Configuration
BASE_URL = "https://127.0.0.1:5000/v1/api"
VERIFY_SSL = False  # self-signed cert

# Trading Configuration
DEFAULT_SYMBOL = "TQQQ"  # Symbol to trade
MAX_POSITION_SIZE = 1.5

# Retry Configuration
MAX_RETRY_ATTEMPTS = 3
RETRY_DELAY = 2
RETRY_BACKOFF = 2