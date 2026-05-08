from binance.client import Client
import pandas as pd
import pandas_ta as ta
import requests
import time

from datetime import datetime, timedelta

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
last_signal_times = {}

COOLDOWN_MINUTES = 30


def send_telegram_message(message):

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }

    requests.post(url, data=payload)


def scan_market(symbol):

    global last_signals
    global last_signal_times

    # Fetch 5m candles
    klines = client.get_klines(
        symbol=symbol,
        interval=Client.KLINE_INTERVAL_5MINUTE,
        limit=100
    )

    # Fetch 1h candles
    higher_klines = client.get_klines(
        symbol=symbol,
        interval=Client.KLINE_INTERVAL_1HOUR,
        limit=100
    )

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

    # Create dataframes
    df = pd.DataFrame(klines, columns=columns)
    higher_df = pd.DataFrame(higher_klines, columns=columns)

    # Convert types
    price_columns = ["open", "high", "low", "close", "volume"]

    for col in price_columns:
        df[col] = df[col].astype(float)
        higher_df[col] = higher_df[col].astype(float)

    # Indicators (5m)
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

    # Indicators (1h)
    higher_df["EMA20"] = ta.ema(higher_df["close"], length=20)
    higher_df["EMA50"] = ta.ema(higher_df["close"], length=50)

    # Use CLOSED candles only
    latest = df.iloc[-2]
    higher_latest = higher_df.iloc[-2]

    previous_candle = df.iloc[-3]

    recent_high = df["high"].iloc[-10:-2].max()
    recent_low = df["low"].iloc[-10:-2].min()   

    # Trends
    trend = (
        "BULLISH"
        if latest["EMA20"] > latest["EMA50"]
        else "BEARISH"
    )

    higher_trend = (
        "BULLISH"
        if higher_latest["EMA20"] > higher_latest["EMA50"]
        else "BEARISH"
    )

    # Filters
    volume_confirmed = (
        latest["volume"] > latest["VOLUME_MA20"] * 0.8
    )

    atr_confirmed = (
        latest["ATR"] > latest["close"] * 0.002
    )

    bullish_breakout = latest["close"] > recent_high
    bearish_breakdown = latest["close"] < recent_low

    # Signal
    signal = "NONE"

    # Confidence scoring
    confidence = 0

    # Entry price
    entry_price = latest["close"]

    # ATR stop distance
    stop_distance = latest["ATR"] * 1.5

    # EMA gap strength
    ema_gap_percent = (
        abs(latest["EMA20"] - latest["EMA50"])
        / latest["close"]
    ) * 100

    # RSI quality
    if 55 <= latest["RSI"] <= 65:
        confidence += 25

    elif 50 <= latest["RSI"] <= 70:
        confidence += 15

    # Volume strength
    volume_ratio = (
        latest["volume"] / latest["VOLUME_MA20"]
    )

    if volume_ratio >= 1.5:
        confidence += 25

    elif volume_ratio >= 1.0:
        confidence += 15

    # ATR strength
    atr_percent = (
        latest["ATR"] / latest["close"]
    ) * 100

    if atr_percent >= 0.5:
        confidence += 25

    elif atr_percent >= 0.2:
        confidence += 15

    # EMA separation
    if ema_gap_percent >= 0.5:
        confidence += 25

    elif ema_gap_percent >= 0.2:
        confidence += 15

    # LONG setup
    if (
        latest["EMA20"] > latest["EMA50"]
        and 50 <= latest["RSI"] <= 70
        and volume_confirmed
        and atr_confirmed
        and higher_trend == "BULLISH"
        and confidence >= 60
        and bullish_breakout
    ):

        signal = "LONG"

        stop_loss = entry_price - stop_distance

        take_profit = (
            entry_price + (stop_distance * 2)
        )

    # SHORT setup
    elif (
        latest["EMA20"] < latest["EMA50"]
        and 30 <= latest["RSI"] <= 50
        and volume_confirmed
        and atr_confirmed
        and higher_trend == "BEARISH"
        and confidence >= 60
        and bearish_breakdown
    ):

        signal = "SHORT"

        stop_loss = entry_price + stop_distance

        take_profit = (
            entry_price - (stop_distance * 2)
        )

    else:
        return

    # Cooldown check
    last_signal_time = last_signal_times.get(symbol)

    if last_signal_time:

        elapsed = datetime.now() - last_signal_time

        if elapsed < timedelta(minutes=COOLDOWN_MINUTES):
            return

    # Prevent duplicate signals
    if signal != last_signals.get(symbol):

        print("==========")
        print(f"Symbol: {symbol}")
        print(f"Price: {latest['close']}")
        print(f"Trend: {trend}")
        print(f"1H Trend: {higher_trend}")

        print(f"EMA20: {latest['EMA20']:.2f}")
        print(f"EMA50: {latest['EMA50']:.2f}")

        print(f"RSI: {latest['RSI']:.2f}")

        print(f"Volume: {latest['volume']:.2f}")
        print(f"Volume MA20: {latest['VOLUME_MA20']:.2f}")
        print(f"Volume Confirmed: {volume_confirmed}")

        print(f"ATR: {latest['ATR']:.2f}")
        print(f"ATR Confirmed: {atr_confirmed}")

        print(f"Confidence: {confidence}%")

        print(f"SIGNAL: {signal}")

        print(f"Entry: {entry_price:.2f}")
        print(f"Stop Loss: {stop_loss:.2f}")
        print(f"Take Profit: {take_profit:.2f}")
        print("Risk/Reward: 1:2")

        print(f"Bullish Breakout: {bullish_breakout}")
        print(f"Bearish Breakdown: {bearish_breakdown}")
        print("==========")

        # Telegram alert
        message = f"""
            🚨 {signal} SIGNAL

            Symbol: {symbol}

            Price: {latest['close']}

            Trend: {trend}
            1H Trend: {higher_trend}

            RSI: {latest['RSI']:.2f}

            Confidence: {confidence}%

            Entry: {entry_price:.2f}
            Stop Loss: {stop_loss:.2f}
            Take Profit: {take_profit:.2f}

            Risk/Reward: 1:2

            Volume Confirmed: {volume_confirmed}
            ATR Confirmed: {atr_confirmed}
            """

        send_telegram_message(message)

        last_signals[symbol] = signal
        last_signal_times[symbol] = datetime.now()

# Continuous scanner loop
while True:

    try:

        for symbol in symbols:
            scan_market(symbol)

    except Exception as e:
        print(f"Error: {e}")

    # Scan every minute
    time.sleep(60)