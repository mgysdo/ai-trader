from binance.client import Client
import pandas as pd

client = Client()

klines = client.get_historical_klines(
    "BTCUSDT",
    Client.KLINE_INTERVAL_1HOUR,
    "90 days ago UTC"
)

data = []

for k in klines:
    data.append({
        "timestamp": k[0],
        "open": float(k[1]),
        "high": float(k[2]),
        "low": float(k[3]),
        "close": float(k[4]),
        "volume": float(k[5]),
    })

df = pd.DataFrame(data)

df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")

df.to_csv("btc_usdt_1h.csv", index=False)

print(df.head())