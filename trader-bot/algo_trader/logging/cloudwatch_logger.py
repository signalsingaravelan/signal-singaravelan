"""CloudWatch logging functionality for AWS EC2 deployment."""

import json
import logging
import socket
import sys
from datetime import datetime
from typing import Optional

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

from algo_trader.utils.config import CLOUDWATCH_LOG_GROUP, CLOUDWATCH_REGION

EC2_METADATA_URL = "http://169.254.169.254/latest/dynamic/instance-identity/document"


class CloudWatchLogger:
    """Dual logger that writes to both CloudWatch and console."""
    
    def __init__(self, log_group: str = None, region: str = None):
        self.log_group = log_group or CLOUDWATCH_LOG_GROUP
        self.region = region or CLOUDWATCH_REGION
        self.sequence_token = None
        self._cloudwatch_initialized = False
        
        self._console = self._create_console_logger()
        self._cloudwatch = None
        self.log_stream = None

    # -------------------------------------------------------------------------
    # Public logging methods
    # -------------------------------------------------------------------------
    
    def info(self, message: str) -> None:
        self._log("INFO", message)
    
    def warning(self, message: str) -> None:
        self._log("WARNING", message)
    
    def error(self, message: str) -> None:
        self._log("ERROR", message)
    
    def debug(self, message: str) -> None:
        self._log("DEBUG", message)

    # -------------------------------------------------------------------------
    # Private methods
    # -------------------------------------------------------------------------

    def _log(self, level: str, message: str) -> None:
        """Route message to console and CloudWatch."""
        getattr(self._console, level.lower())(message)
        self._send_to_cloudwatch(level, message)
    
    def initialize_cloudwatch(self, account_id: str) -> None:
        """Initialize CloudWatch with account-specific log group."""
        if self._cloudwatch_initialized:
            return
        
        # Append account ID to log group name
        self.log_group = f"{self.log_group}-{account_id}"
        self._cloudwatch, self.log_stream = self._create_cloudwatch_client()
        self._cloudwatch_initialized = True

    def _send_to_cloudwatch(self, level: str, message: str) -> None:
        """Send a single log event to CloudWatch."""
        if not self._cloudwatch:
            return
        
        try:
            params = {
                "logGroupName": self.log_group,
                "logStreamName": self.log_stream,
                "logEvents": [{
                    "timestamp": int(datetime.now().timestamp() * 1000),
                    "message": f"[{level}] {message}"
                }]
            }
            if self.sequence_token:
                params["sequenceToken"] = self.sequence_token
            
            response = self._cloudwatch.put_log_events(**params)
            self.sequence_token = response.get("nextSequenceToken")
        except Exception:
            pass  # Silently fail - console logging is the fallback

    def _create_console_logger(self) -> logging.Logger:
        """Create a standard console logger."""
        logger = logging.getLogger("algo_trading")
        logger.setLevel(logging.INFO)
        logger.handlers.clear()
        
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        logger.addHandler(handler)
        
        return logger

    def _create_cloudwatch_client(self) -> tuple[Optional[boto3.client], str]:
        """Initialize CloudWatch client and create log group/stream."""
        log_stream = self._generate_log_stream_name()
        
        try:
            client = boto3.client("logs", region_name=self.region)
            self._ensure_log_group_exists(client)
            self._ensure_log_stream_exists(client, log_stream)
            self._console.info(f"CloudWatch initialized: {self.log_group}/{log_stream}")
            return client, log_stream
        except (NoCredentialsError, ClientError, Exception) as e:
            self._console.warning(f"CloudWatch unavailable: {e}. Using console only.")
            return None, log_stream

    def _ensure_log_group_exists(self, client) -> None:
        """Create log group if it doesn't exist."""
        try:
            client.create_log_group(logGroupName=self.log_group)
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceAlreadyExistsException":
                raise

    def _ensure_log_stream_exists(self, client, log_stream: str) -> None:
        """Create log stream if it doesn't exist."""
        try:
            client.create_log_stream(logGroupName=self.log_group, logStreamName=log_stream)
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceAlreadyExistsException":
                raise

    def _generate_log_stream_name(self) -> str:
        """Generate unique log stream name from instance ID and timestamp."""
        instance_id = self._get_instance_id()
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return f"{instance_id}-{timestamp}"

    def _get_instance_id(self) -> str:
        """Get EC2 instance ID, falling back to hostname if not on EC2."""
        try:
            import urllib.request
            with urllib.request.urlopen(EC2_METADATA_URL, timeout=2) as response:
                metadata = json.loads(response.read().decode())
                return metadata.get("instanceId", socket.gethostname())
        except Exception:
            return socket.gethostname()


# -----------------------------------------------------------------------------
# Module-level singleton
# -----------------------------------------------------------------------------

_logger: Optional[CloudWatchLogger] = None


def get_logger() -> CloudWatchLogger:
    """Get or create the global CloudWatch logger instance."""
    global _logger
    if _logger is None:
        _logger = CloudWatchLogger()
    return _logger
