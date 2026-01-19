"""Trade data model."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Trade:
    """Represents a trading transaction."""
    
    account_id: str
    action: str  # "Buy" or "Sell"
    symbol: str
    dollar_amount: float
    shares: float
    order_id: Optional[str] = None
    timestamp: Optional[datetime] = None
    
    def __post_init__(self):
        """Set timestamp if not provided."""
        if self.timestamp is None:
            self.timestamp = datetime.now()
        
        # Round shares to 2 decimal places
        self.shares = round(self.shares, 2)
    
    @property
    def formatted_timestamp(self) -> str:
        """Get formatted timestamp string."""
        return self.timestamp.strftime("%Y-%m-%d %H:%M:%S")
    
    def to_dict(self) -> dict:
        """Convert trade to dictionary for Excel/logging."""
        return {
            "Date": self.formatted_timestamp,
            "OrderId": self.order_id or f"ORD_{self.timestamp.strftime('%Y%m%d_%H%M%S')}",
            "Action": self.action,
            "Symbol": self.symbol,
            "Dollar Amount": self.dollar_amount,
            "Shares": self.shares
        }