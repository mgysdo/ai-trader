from binance.client import Client
import pandas as pd
import pandas_ta as ta
import requests
import time
import os
import csv
from dotenv import load_dotenv

from datetime import UTC, datetime, timedelta

load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

if not API_KEY or not API_SECRET:
    raise ValueError(
        "Set BINANCE_API_KEY and BINANCE_API_SECRET environment variables."
    )

client = Client(API_KEY, API_SECRET)

symbols = [
    "BTCUSDT",
]

last_signals = {}
last_signal_times = {}
last_processed_close_times = {}

COOLDOWN_MINUTES = 30

# Live-readiness mode: simulate trades until results are stable.
PAPER_TRADING = True
# $1000 account safety defaults.
DAILY_TARGET_USD = 8.0
DAILY_MAX_LOSS_USD = 10.0
RISK_PER_TRADE_USD = 2.5
RR_RATIO = 2.5
ATR_PERCENT_MIN = 0.4
COMMISSION_RATE = 0.001
SLIPPAGE_RATE = 0.0005
TRADES_CSV_FILE = "trades.csv"

paper_positions = {}
daily_pnl_usd = 0.0
daily_date = datetime.now(UTC).date()
trading_paused = False
daily_trade_entries = 0
daily_trade_exits = 0
daily_win_trades = 0
daily_loss_trades = 0


def send_daily_summary(summary_date):
    summary = (
        f"DAILY SUMMARY {summary_date} UTC\n"
        f"Net PnL: ${daily_pnl_usd:.2f}\n"
        f"Entries: {daily_trade_entries}\n"
        f"Exits: {daily_trade_exits}\n"
        f"Wins: {daily_win_trades}\n"
        f"Losses: {daily_loss_trades}\n"
        f"Open Positions: {len(paper_positions)}\n"
        f"Paused: {trading_paused}"
    )

    print(summary)
    send_telegram_message(summary)


def reset_daily_state_if_needed():
    global daily_date
    global daily_pnl_usd
    global trading_paused
    global daily_trade_entries
    global daily_trade_exits
    global daily_win_trades
    global daily_loss_trades

    today = datetime.now(UTC).date()

    if today != daily_date:
        send_daily_summary(daily_date)
        daily_date = today
        daily_pnl_usd = 0.0
        trading_paused = False
        daily_trade_entries = 0
        daily_trade_exits = 0
        daily_win_trades = 0
        daily_loss_trades = 0
        print("New UTC day started. Daily PnL reset.")


def check_daily_guardrails():
    global trading_paused

    if trading_paused:
        return

    if daily_pnl_usd >= DAILY_TARGET_USD:
        trading_paused = True
        msg = (
            f"Daily target hit: +${daily_pnl_usd:.2f}. "
            "Trading paused until next UTC day."
        )
        print(msg)
        send_telegram_message(msg)

    elif daily_pnl_usd <= -DAILY_MAX_LOSS_USD:
        trading_paused = True
        msg = (
            f"Daily max loss hit: ${daily_pnl_usd:.2f}. "
            "Trading paused until next UTC day."
        )
        print(msg)
        send_telegram_message(msg)


def update_paper_position(symbol, current_price):
    global daily_pnl_usd
    global daily_trade_exits
    global daily_win_trades
    global daily_loss_trades

    position = paper_positions.get(symbol)

    if not position:
        return

    side = position["side"]
    sl = position["sl"]
    tp = position["tp"]
    qty = position["qty"]
    entry = position["entry"]

    exit_price = None
    exit_reason = None

    if side == "LONG":
        if current_price <= sl:
            exit_price = sl
            exit_reason = "SL"
        elif current_price >= tp:
            exit_price = tp
            exit_reason = "TP"

    elif side == "SHORT":
        if current_price >= sl:
            exit_price = sl
            exit_reason = "SL"
        elif current_price <= tp:
            exit_price = tp
            exit_reason = "TP"

    if exit_price is None:
        return

    if side == "LONG":
        gross_pnl = (exit_price - entry) * qty
    else:
        gross_pnl = (entry - exit_price) * qty

    notional_entry = abs(entry * qty)
    notional_exit = abs(exit_price * qty)
    fees = (notional_entry + notional_exit) * COMMISSION_RATE
    slippage = (notional_entry + notional_exit) * SLIPPAGE_RATE
    pnl = gross_pnl - fees - slippage

    daily_pnl_usd += pnl
    daily_trade_exits += 1

    if pnl >= 0:
        daily_win_trades += 1
    else:
        daily_loss_trades += 1

    print(
        f"PAPER EXIT {symbol} {side} {exit_reason} "
        f"Gross=${gross_pnl:.2f} Fees+Slip=${fees + slippage:.2f} "
        f"NetPnL=${pnl:.2f} DailyPnL=${daily_pnl_usd:.2f}"
    )

    send_telegram_message(
        f"PAPER EXIT {symbol} {side} {exit_reason} "
        f"Gross=${gross_pnl:.2f} Fees+Slip=${fees + slippage:.2f} "
        f"NetPnL=${pnl:.2f} DailyPnL=${daily_pnl_usd:.2f}"
    )

    # Log trade to CSV
    log_trade_to_csv(
        timestamp=datetime.now(UTC).isoformat(),
        symbol=symbol,
        side=side,
        entry_price=entry,
        sl=sl,
        tp=tp,
        exit_price=exit_price,
        exit_reason=exit_reason,
        qty=qty,
        gross_pnl=gross_pnl,
        fees_slippage=fees + slippage,
        net_pnl=pnl
    )

    del paper_positions[symbol]
    check_daily_guardrails()


def send_telegram_message(message):

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
    }

    requests.post(url, data=payload, timeout=10)


def initialize_trades_csv():
    """Create trades.csv with headers if it doesn't exist."""
    if not os.path.exists(TRADES_CSV_FILE):
        with open(TRADES_CSV_FILE, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp",
                "symbol",
                "side",
                "entry_price",
                "sl",
                "tp",
                "exit_price",
                "exit_reason",
                "qty",
                "gross_pnl",
                "fees_slippage",
                "net_pnl"
            ])


def log_trade_to_csv(timestamp, symbol, side, entry_price, sl, tp, exit_price, exit_reason, qty, gross_pnl, fees_slippage, net_pnl):
    """Append a completed trade to trades.csv."""
    try:
        with open(TRADES_CSV_FILE, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                timestamp,
                symbol,
                side,
                f"{entry_price:.2f}",
                f"{sl:.2f}",
                f"{tp:.2f}",
                f"{exit_price:.2f}",
                exit_reason,
                f"{qty:.6f}",
                f"{gross_pnl:.2f}",
                f"{fees_slippage:.2f}",
                f"{net_pnl:.2f}"
            ])
    except Exception as e:
        print(f"Error logging trade to CSV: {e}")


def scan_market(symbol):

    global last_signals
    global last_signal_times
    global last_processed_close_times
    global daily_trade_entries

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
    df["EMA9"] = ta.ema(df["close"], length=9)
    df["EMA21"] = ta.ema(df["close"], length=21)

    df["RSI"] = ta.rsi(df["close"], length=14)

    df["VOLUME_MA20"] = ta.sma(df["volume"], length=20)

    df["ATR"] = ta.atr(
        high=df["high"],
        low=df["low"],
        close=df["close"],
        length=14
    )

    # Indicators (1h)
    higher_df["EMA9"] = ta.ema(higher_df["close"], length=9)
    higher_df["EMA21"] = ta.ema(higher_df["close"], length=21)

    # Use CLOSED candles only
    latest = df.iloc[-2]
    higher_latest = higher_df.iloc[-2]

    latest_close_time = int(latest["close_time"])
    if last_processed_close_times.get(symbol) == latest_close_time:
        return
    last_processed_close_times[symbol] = latest_close_time

    update_paper_position(symbol, latest["close"])

    slow_ema_prev = df["EMA21"].iloc[-3]

    # Trends
    trend = (
        "BULLISH"
        if latest["EMA9"] > latest["EMA21"]
        else "BEARISH"
    )

    higher_trend = (
        "BULLISH"
        if higher_latest["EMA9"] > higher_latest["EMA21"]
        else "BEARISH"
    )

    # Signal
    signal = "NONE"

    # Entry price
    entry_price = latest["close"]

    # ATR stop distance
    stop_distance = latest["ATR"] * 1.5

    # ATR strength
    atr_percent = (
        latest["ATR"] / latest["close"]
    ) * 100

    # LONG setup
    if (
        latest["EMA9"] > latest["EMA21"]
        and latest["close"] > latest["EMA21"]
        and latest["EMA21"] > slow_ema_prev
        and 60 <= latest["RSI"] <= 70
        and atr_percent >= ATR_PERCENT_MIN
        and higher_trend == "BULLISH"
    ):

        signal = "LONG"

        stop_loss = entry_price - stop_distance

        take_profit = (
            entry_price + (stop_distance * RR_RATIO)
        )

    else:
        return

    # Cooldown check
    last_signal_time = last_signal_times.get(symbol)

    if last_signal_time:

        elapsed = datetime.now(UTC) - last_signal_time

        if elapsed < timedelta(minutes=COOLDOWN_MINUTES):
            return

    # Prevent duplicate signals
    if signal != last_signals.get(symbol):

        if trading_paused:
            return

        if PAPER_TRADING and symbol in paper_positions:
            return

        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit <= 0:
            return

        qty = RISK_PER_TRADE_USD / risk_per_unit

        if qty <= 0:
            return

        if PAPER_TRADING:
            paper_positions[symbol] = {
                "side": signal,
                "entry": entry_price,
                "sl": stop_loss,
                "tp": take_profit,
                "qty": qty,
                "opened_at": datetime.now(UTC),
            }
            daily_trade_entries += 1

        print("==========")
        print(f"Symbol: {symbol}")
        print(f"Price: {latest['close']}")
        print(f"Trend: {trend}")
        print(f"1H Trend: {higher_trend}")

        print(f"EMA9: {latest['EMA9']:.2f}")
        print(f"EMA21: {latest['EMA21']:.2f}")

        print(f"RSI: {latest['RSI']:.2f}")

        print(f"ATR: {latest['ATR']:.2f}")
        print(f"ATR %: {atr_percent:.2f}")

        print(f"SIGNAL: {signal}")

        print(f"Entry: {entry_price:.2f}")
        print(f"Stop Loss: {stop_loss:.2f}")
        print(f"Take Profit: {take_profit:.2f}")
        print(f"Qty: {qty:.6f}")
        print(f"Mode: {'PAPER' if PAPER_TRADING else 'LIVE'}")
        print(f"Daily PnL: ${daily_pnl_usd:.2f}")
        print(f"Risk/Reward: 1:{RR_RATIO}")
        print("==========")

        # Telegram alert
        message = f"""
            🚨 {signal} SIGNAL

            Symbol: {symbol}

            Price: {latest['close']}

            Trend: {trend}
            1H Trend: {higher_trend}

            RSI: {latest['RSI']:.2f}
            ATR %: {atr_percent:.2f}

            Entry: {entry_price:.2f}
            Stop Loss: {stop_loss:.2f}
            Take Profit: {take_profit:.2f}
            Qty: {qty:.6f}
            Mode: {'PAPER' if PAPER_TRADING else 'LIVE'}
            Daily PnL: ${daily_pnl_usd:.2f}

            Risk/Reward: 1:{RR_RATIO}
            """

        send_telegram_message(message)

        last_signals[symbol] = signal
        last_signal_times[symbol] = datetime.now(UTC)

# Initialize CSV file
initialize_trades_csv()

# Continuous scanner loop
while True:

    try:

        reset_daily_state_if_needed()

        print(
            f"[{datetime.now(UTC).isoformat()}] "
            f"Scan started | symbols={len(symbols)} "
            f"open_paper_positions={len(paper_positions)} "
            f"daily_pnl=${daily_pnl_usd:.2f} "
            f"paused={trading_paused}"
        )

        for symbol in symbols:
            scan_market(symbol)

        print(f"[{datetime.now(UTC).isoformat()}] Scan completed")

    except Exception as e:
        print(f"Error: {e}")

    # Scan every minute
    time.sleep(60)