"""Load application secrets from AWS Secrets Manager."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import ClientError

from algo_trader.utils.config import SECRETS_MANAGER_REGION, SECRETS_MANAGER_SECRET_NAME

_secrets_cache: Optional[Dict[str, Any]] = None


def get_secrets() -> Dict[str, Any]:
    """Fetch and cache the SignalSingaravelanSecrets JSON from Secrets Manager."""
    global _secrets_cache
    if _secrets_cache is not None:
        return _secrets_cache

    try:
        client = boto3.client("secretsmanager", region_name=SECRETS_MANAGER_REGION)
        response = client.get_secret_value(SecretId=SECRETS_MANAGER_SECRET_NAME)
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        raise RuntimeError(
            f"Failed to retrieve secret '{SECRETS_MANAGER_SECRET_NAME}' "
            f"from Secrets Manager ({error_code}): {e}"
        ) from e
    except Exception as e:
        raise RuntimeError(
            f"Unexpected error retrieving secret '{SECRETS_MANAGER_SECRET_NAME}': {e}"
        ) from e

    secret_string = response.get("SecretString")
    if not secret_string:
        raise RuntimeError(
            f"Secret '{SECRETS_MANAGER_SECRET_NAME}' has no SecretString payload"
        )

    try:
        secret_data = json.loads(secret_string)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Secret '{SECRETS_MANAGER_SECRET_NAME}' is not valid JSON: {e}"
        ) from e

    if not isinstance(secret_data, dict) or not secret_data:
        raise RuntimeError(
            f"Secret '{SECRETS_MANAGER_SECRET_NAME}' must be a non-empty JSON object"
        )

    _secrets_cache = secret_data
    return _secrets_cache


def get_secret_value(key: str) -> Optional[str]:
    """Return one key from the cached secrets dict, or None if missing/empty."""
    value = get_secrets().get(key)
    if value is None or value == "":
        return None
    return str(value)


def load_secrets() -> Dict[str, Any]:
    """Load secrets, hydrate Alpaca keys into the environment, and cache the dict.

    Fails hard if Secrets Manager is unreachable.
    Individual Alpaca keys are validated later by AccountConfig.resolve_credentials().
    TELEGRAM_BOT_TOKEN and MASSIVE_API_KEY are read on demand via get_secret_value().
    """
    secrets = get_secrets()

    for key, value in secrets.items():
        if key.startswith("ALPACA_") and value is not None and value != "":
            os.environ[key] = str(value)

    return secrets


def clear_secrets_cache() -> None:
    """Clear the in-process cache (intended for tests)."""
    global _secrets_cache
    _secrets_cache = None
