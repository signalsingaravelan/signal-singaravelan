"""Enumerations used throughout the application."""

from enum import Enum

class Signal(Enum):
    """Trading signal enumeration."""
    BULLISH = 1
    BEARISH = 2
    NEUTRAL = 3
