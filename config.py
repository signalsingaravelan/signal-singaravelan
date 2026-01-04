"""Configuration settings for the IBKR trading client."""

# IBKR Web API Configuration
BASE_URL = "https://127.0.0.1:5000/v1/api"
VERIFY_SSL = False  # self-signed cert

# Trading Configuration
SYMBOL = "TQQQ"  # Primary trading symbol
TQQQ_CONTRACT_ID = 72539702 # ContractID for TQQQ
MAX_PER_ORDER = 10

# Retry Configuration
MAX_RETRY_ATTEMPTS = 3
RETRY_DELAY = 2
RETRY_BACKOFF = 2