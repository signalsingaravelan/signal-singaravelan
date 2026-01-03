"""Trading strategy implementation."""

from utils import Signal


class TradingStrategy:
    """Simple trading strategy that returns signals."""
    
    def get_signal(self) -> Signal:
        """
        Get trading signal based on market analysis.
        
        Currently returns BULLISH as a placeholder.
        This can be extended with actual market analysis logic.
        """
        # TODO: Implement actual strategy logic
        # This could include technical indicators, fundamental analysis, etc.
        return Signal.BULLISH