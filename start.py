import os
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient

# Load .env file
load_dotenv()

api_key = os.getenv("ALPACA_API_KEY")
secret_key = os.getenv("ALPACA_SECRET_KEY")

# Connect to paper trading
client = TradingClient(
    api_key=api_key,
    secret_key=secret_key,
    paper=True
)

account = client.get_account()

print("Account Status:", account.status)
print("Cash:", account.cash)
print("Buying Power:", account.buying_power)
print("Portfolio Value:", account.portfolio_value)