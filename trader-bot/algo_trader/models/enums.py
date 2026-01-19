"""Enumerations used throughout the application."""

from enum import Enum


class Signal(Enum):
    """Trading signal enumeration."""
    BULLISH = 1
    BEARISH = 2
    NEUTRAL = 3
    CLOSED = 4


class Severity(Enum):
    """Notification severity enumeration."""
    INFO = 1
    WARNING = 2
    ERROR = 3
    DEBUG = 4