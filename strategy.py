"""Trading strategy implementation."""

from utils import Signal

class TradingStrategy:
    """Simple trading strategy that returns market signals."""
    
    def get_signal(self) -> Signal:
        """
        Get the current market signal.
        
        This is a placeholder implementation that always returns BULLISH.
        In a real implementation, this would analyze market data, technical
        indicators, or other factors to determine the appropriate signal.
        """
        # TODO: Implement actual strategy logic
        return Signal.BULLISH