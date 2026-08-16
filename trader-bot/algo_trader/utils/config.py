"""Configuration settings for the Alpaca trading client."""

# Accounts Configuration
ACCOUNTS_CONFIG_PATH = "accounts.yaml"

# Trading Configuration
MIN_CASH_THRESHOLD = 5.0   # Minimum cash required to place a trade
MIN_ORDER_AMOUNT = 1.0     # Alpaca's minimum notional order size

# Retry Configuration
MAX_RETRY_ATTEMPTS = 3
RETRY_DELAY = 2
RETRY_BACKOFF = 2

# CloudWatch Configuration
CLOUDWATCH_LOG_GROUP = "signal-singaravelan"
CLOUDWATCH_REGION = "us-east-1"

# S3 Configuration
S3_BUCKET_NAME = "signal-singaravelan"  # Replace with your S3 bucket name
S3_REGION = "us-east-1"
S3_KEY_PREFIX = "trade-history/"  # Optional prefix for organizing files

# Massive.com Configuration
MASSIVE_API_KEY = "8xIyTYAdFkzyMbpspyDDMjjqyx98PhnZ"

# Notification Configuration
# Email settings (using AWS SES)
EMAIL_FROM = "signalsingaravelan@gmail.com"  # Replace with your verified SES email
EMAIL_TO = "ac.vino@gmail.com"        # Replace with your email
EMAIL_REGION = "us-east-1"

# Telegram settings
TELEGRAM_CHAT_ID = "-1003650035424"
SECRETS_MANAGER_SECRET_NAME = "SignalSingaravelanSecrets"
SECRETS_MANAGER_REGION = "us-east-1"