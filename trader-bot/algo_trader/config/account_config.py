"""Loads and validates the multi-account trading configuration (accounts.yaml)."""

import os
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import yaml

from algo_trader.utils.config import ACCOUNTS_CONFIG_PATH

ALLOCATION_TOTAL_TOLERANCE = 0.01  # percentage points


@dataclass
class AccountConfig:
    """Configuration for a single Alpaca account."""

    name: str
    enabled: bool
    paper: bool
    api_key_env: str
    api_secret_env: str
    allocations: Dict[str, float] = field(default_factory=dict)
    performance_start_date: Optional[str] = None

    def resolve_credentials(self) -> Tuple[str, str]:
        """Read this account's API key/secret from environment variables."""
        api_key = os.environ.get(self.api_key_env)
        api_secret = os.environ.get(self.api_secret_env)

        if not api_key or not api_secret:
            raise ValueError(
                f"Missing Alpaca credentials for account '{self.name}': "
                f"expected environment variables {self.api_key_env} and {self.api_secret_env}"
            )

        return api_key, api_secret


def _parse_performance_start_date(name: str, raw_value, path: str) -> Optional[str]:
    """Normalize and validate an optional ISO performance start date."""
    if raw_value is None or raw_value == "":
        return None

    value = str(raw_value).strip()
    if not value:
        return None

    try:
        datetime.fromisoformat(value)
    except ValueError as e:
        raise ValueError(
            f"Account '{name}' has invalid performance_start_date '{value}' "
            f"(expected ISO date YYYY-MM-DD) in {path}"
        ) from e

    return value


def load_accounts(path: str = None) -> List[AccountConfig]:
    """Load and validate all account configs from accounts.yaml."""
    path = path or ACCOUNTS_CONFIG_PATH

    with open(path, "r") as f:
        data = yaml.safe_load(f) or {}

    raw_accounts = data.get("accounts", [])
    if not raw_accounts:
        raise ValueError(f"No accounts defined in {path}")

    accounts = []
    seen_names = set()

    for raw in raw_accounts:
        name = raw.get("name")
        if not name:
            raise ValueError(f"Account entry in {path} is missing a 'name'")
        if name in seen_names:
            raise ValueError(f"Duplicate account name '{name}' in {path}")
        seen_names.add(name)

        enabled = raw.get("enabled", True)
        allocations = raw.get("allocations", {}) or {}

        if enabled:
            total = sum(allocations.values())
            if abs(total - 100.0) > ALLOCATION_TOTAL_TOLERANCE:
                raise ValueError(
                    f"Account '{name}' allocations sum to {total}%, expected 100% (in {path})"
                )

        api_key_env = raw.get("api_key_env")
        api_secret_env = raw.get("api_secret_env")
        if enabled and (not api_key_env or not api_secret_env):
            raise ValueError(
                f"Account '{name}' must define 'api_key_env' and 'api_secret_env' (in {path})"
            )

        performance_start_date = _parse_performance_start_date(
            name, raw.get("performance_start_date"), path
        )

        accounts.append(AccountConfig(
            name=name,
            enabled=enabled,
            paper=raw.get("paper", True),
            api_key_env=api_key_env,
            api_secret_env=api_secret_env,
            allocations=allocations,
            performance_start_date=performance_start_date,
        ))

    return accounts


def get_enabled_accounts(path: str = None) -> List[AccountConfig]:
    """Load account configs and return only the enabled ones."""
    return [account for account in load_accounts(path) if account.enabled]
