"""Main entry point for the trading bot."""

import subprocess
import sys
import importlib.util

from trading_bot import TradingBot


def install_dependencies():
    """Install required dependencies if they're missing."""
    required_packages = {
        'requests': 'requests>=2.31.0',
        'yfinance': 'yfinance>=0.2.18',
        'urllib3': 'urllib3>=2.0.0',
        'ibind': 'ibind>=1.0.0'
    }
    
    missing_packages = []
    
    # Check which packages are missing
    for package_name, pip_name in required_packages.items():
        if importlib.util.find_spec(package_name) is None:
            missing_packages.append(pip_name)
    
    # Install missing packages
    if missing_packages:
        print(f"Installing missing dependencies: {', '.join(missing_packages)}")
        try:
            subprocess.check_call([
                sys.executable, "-m", "pip", "install"
            ] + missing_packages)
            print("Dependencies installed successfully!")
        except subprocess.CalledProcessError as e:
            print(f"Failed to install dependencies: {e}")
            print("Please install manually using: pip install -r requirements.txt")
            sys.exit(1)
    else:
        print("All dependencies are already installed.")


def main():
    """Run the trading bot."""
    # Install dependencies if needed
    install_dependencies()
    
    # Run the bot
    bot = TradingBot()
    bot.execute_trade()


if __name__ == "__main__":
    main()