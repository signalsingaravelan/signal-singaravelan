"""Main entry point for the Alpaca trading application."""

from algo_trader import Trader
from algo_trader.utils.secrets import load_secrets


def main():
    """Main function to execute trading operations."""
    load_secrets()
    trader = Trader()
    trader.execute_trade()


if __name__ == "__main__":
    main()
