"""Utility decorators."""

import functools
import time


def retry(max_attempts=3, delay=2, backoff=2, no_retry_exceptions=None):
    """Retry decorator for handling transient failures.
    
    Args:
        max_attempts: Maximum number of retry attempts
        delay: Initial delay between retries in seconds
        backoff: Multiplier for delay after each retry
        no_retry_exceptions: List of exception types that should not be retried
    """
    if no_retry_exceptions is None:
        no_retry_exceptions = []
    
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            attempts = 0
            wait = delay
            while attempts < max_attempts:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    # Check if this exception type should not be retried
                    if any(isinstance(e, exc_type) for exc_type in no_retry_exceptions):
                        raise  # Re-raise immediately without retry
                    
                    attempts += 1
                    print(f"{func.__name__} failed: {e}. Retry {attempts}/{max_attempts}")
                    if attempts < max_attempts:
                        time.sleep(wait)
                        wait *= backoff
            raise Exception(f"{func.__name__} failed after {max_attempts} retries")
        return wrapper
    return decorator
