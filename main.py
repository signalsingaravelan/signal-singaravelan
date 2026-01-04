"""Main entry point for the IBKR trading application."""

from algo_trader import Trader

def main():
    """Main function to execute trading operations."""
    trader = Trader()
    trader.execute_trade()


if __name__ == "__main__":
    main()
