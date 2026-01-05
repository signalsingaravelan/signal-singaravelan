"""Configuration settings for the IBKR trading client."""

# IBKR Web API Configuration
BASE_URL = "https://127.0.0.1:5000/v1/api"
VERIFY_SSL = False  # self-signed cert

# Trading Configuration
SYMBOL = "TQQQ"
TQQQ_CONTRACT_ID = 72539702
MAX_PER_ORDER = 10

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

# Notification Configuration
# Email settings (using AWS SES)
EMAIL_FROM = "signalsingaravelan@gmail.com"  # Replace with your verified SES email
EMAIL_TO = "asubbu87@gmail.com"        # Replace with your email
EMAIL_REGION = "us-east-1"

# Telegram settings
TELEGRAM_CHAT_ID = "-1003650035424"
SECRETS_MANAGER_SECRET_NAME = "SignalSingaravelanSecrets"
SECRETS_MANAGER_REGION = "us-east-1"