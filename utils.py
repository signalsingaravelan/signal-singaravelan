"""Utility functions and decorators."""

import functools
import time
from enum import Enum


def retry(max_attempts=3, delay=2, backoff=2):
    """Retry decorator for handling transient failures."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            attempts = 0
            wait = delay
            while attempts < max_attempts:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    attempts += 1
                    print(f"{func.__name__} failed: {e}. Retry {attempts}/{max_attempts}")
                    if attempts < max_attempts:
                        time.sleep(wait)
                        wait *= backoff
            raise Exception(f"{func.__name__} failed after {max_attempts} retries")
        return wrapper
    return decorator


class Signal(Enum):
    """Trading signal enumeration."""
    BULLISH = 1
    BEARISH = 2
    NEUTRAL = 3