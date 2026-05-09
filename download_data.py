from binance.client import Client
import pandas as pd

client = Client()

symbol = "BTCUSDT"
interval = Client.KLINE_INTERVAL_5MINUTE

klines = client.get_historical_klines(
    symbol,
    interval,
    "90 days ago UTC"
)

df = pd.DataFrame(klines, columns=[
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_asset_volume",
    "number_of_trades",
    "taker_buy_base_asset_volume",
    "taker_buy_quote_asset_volume",
    "ignore"
])

df = df[[
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume"
]]

df["timestamp"] = pd.to_datetime(
    df["timestamp"],
    unit="ms"
)

numeric_cols = [
    "open",
    "high",
    "low",
    "close",
    "volume"
]

df[numeric_cols] = df[numeric_cols].astype(float)

df.to_csv(
    "btc_usdt_5m.csv",
    index=False
)

print(df.head())

print("Saved btc_usdt_5m.csv")