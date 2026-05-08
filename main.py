from binance.client import Client
import pandas as pd
import pandas_ta as ta
import time
import requests

API_KEY = "NVXqXapN5RE5NmEX9tJ4RjDALMAoAOZFXQ90vSzgdk12qmKYCv81OAlQbYI4RV6q"
API_SECRET = "3qGBW7YvHq0HwYxxOGHcL0mESZRVbNkc17PjUi8TcMcOJuTmJbm5HHjnvn9qGXhd"

TELEGRAM_BOT_TOKEN = "8218143691:AAG7wgsV7S8P1uncJMuf6nk8oN92zwdesEA"
TELEGRAM_CHAT_ID = "1100684351"

client = Client(API_KEY, API_SECRET)

symbols = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT"
]

last_signals = {}

def scan_market(symbol):

    global last_signals

    # Fetch candles
    klines = client.get_klines(
        symbol=symbol,
        interval=Client.KLINE_INTERVAL_5MINUTE,
        limit=100
    )

    # Create dataframe
    columns = [
        "open_time",
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
    ]

    df = pd.DataFrame(klines, columns=columns)

    # Convert types
    price_columns = ["open", "high", "low", "close", "volume"]

    for col in price_columns:
        df[col] = df[col].astype(float)

    # Calculate indicators
    df["EMA20"] = ta.ema(df["close"], length=20)
    df["EMA50"] = ta.ema(df["close"], length=50)

    df["RSI"] = ta.rsi(df["close"], length=14)

    df["VOLUME_MA20"] = ta.sma(df["volume"], length=20)

    df["ATR"] = ta.atr(
    high=df["high"],
    low=df["low"],
    close=df["close"],
    length=14
)

    # Use last FULLY CLOSED candle
    latest = df.iloc[-2]

    # Trend
    trend = "BULLISH" if latest["EMA20"] > latest["EMA50"] else "BEARISH"

    # Volume confirmation
    volume_confirmed = (
        latest["volume"] > latest["VOLUME_MA20"] * 0.8
    )

    atr_confirmed = latest["ATR"] > latest["close"] * 0.002

    # Signal logic
    signal = "NONE"

    if (
        latest["EMA20"] > latest["EMA50"]
        and 50 <= latest["RSI"] <= 70
        and volume_confirmed
        and atr_confirmed
    ):
        signal = "LONG"

    elif (
        latest["EMA20"] < latest["EMA50"]
        and 30 <= latest["RSI"] <= 50
        and volume_confirmed
        and atr_confirmed
    ):
        signal = "SHORT"

    # Print only when signal changes
    if signal != last_signals.get(symbol):

        print("==========")
        print(f"Symbol: {symbol}")
        print(f"Price: {latest['close']}")
        print(f"Trend: {trend}")
        print(f"EMA20: {latest['EMA20']:.2f}")
        print(f"EMA50: {latest['EMA50']:.2f}")
        print(f"RSI: {latest['RSI']:.2f}")
        print(f"Volume: {latest['volume']:.2f}")
        print(f"Volume MA20: {latest['VOLUME_MA20']:.2f}")
        print(f"Volume Confirmed: {volume_confirmed}")
        print(f"SIGNAL: {signal}")
        print(f"ATR: {latest['ATR']:.2f}")
        print(f"ATR Confirmed: {atr_confirmed}")
        print("==========")

        message = f"""
        🚨 {signal} SIGNAL

        Symbol: {symbol}
        Price: {latest['close']}
        Trend: {trend}
        RSI: {latest['RSI']:.2f}

        Volume Confirmed: {volume_confirmed}
        ATR Confirmed: {atr_confirmed}
        """

        send_telegram_message(message)
        last_signals[symbol] = signal

def send_telegram_message(message):

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }

    requests.post(url, data=payload)


# Continuous scanner loop
while True:

    try:
        for symbol in symbols:
            scan_market(symbol)

    except Exception as e:
        print(f"Error: {e}")

    # Scan every 60 seconds
    time.sleep(60)