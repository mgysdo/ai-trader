from __future__ import annotations

import csv
import os
import time
import warnings
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, time as dt_time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from binance.client import Client
from dotenv import load_dotenv


warnings.filterwarnings(
    "ignore",
    message="SettingWithCopyWarning",
    category=UserWarning,
)


load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

DATA_SOURCE = os.getenv("EURUSD_DATA_SOURCE", "yfinance").strip().lower()
BINANCE_SYMBOL = os.getenv("BINANCE_SYMBOL", "EURUSDT").strip().upper()
BINANCE_LIMIT = int(os.getenv("BINANCE_LIMIT", "1000"))

TICKER = "EURUSD=X"
FAST_INTERVAL = "5m"
SLOW_INTERVAL = "15m"
LOOKBACK_PERIOD = "60d"
NY = ZoneInfo("America/New_York")

PAPER_TRADING = True
COOLDOWN_MINUTES = 20
SCAN_SECONDS = 300

DAILY_TARGET_USD = 8.0
DAILY_MAX_LOSS_USD = 10.0
RISK_PER_TRADE_USD = 2.5
RR_RATIO = 2.0
ATR_BUFFER = 0.35

TRADES_CSV_FILE = "eurusd_trades.csv"

if BINANCE_API_KEY and BINANCE_API_SECRET:
    binance_client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)
else:
    # Public klines are available without API credentials.
    binance_client = Client()


def instrument_symbol():
    return BINANCE_SYMBOL if DATA_SOURCE == "binance" else TICKER


def ema(series, period):
    return pd.Series(series).ewm(span=period, adjust=False).mean()


def rsi(series, period=14):
    series = pd.Series(series)
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def atr(high, low, close, period=14):
    high = pd.Series(high)
    low = pd.Series(low)
    close = pd.Series(close)
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def normalize_ohlc(df):
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]
    df = df.rename(columns={c: c.lower() for c in df.columns})
    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[keep]
    if df.index.tz is None:
        df.index = df.index.tz_localize(UTC)
    else:
        df.index = df.index.tz_convert(UTC)
    return df.sort_index()


def download_data_yfinance(interval, period):
    raw = yf.download(
        TICKER,
        interval=interval,
        period=period,
        auto_adjust=False,
        progress=False,
        prepost=False,
        threads=False,
    )
    if raw.empty:
        raise RuntimeError(f"No data returned for {TICKER} {interval} {period}")
    return normalize_ohlc(raw)


def download_data_binance(interval):
    interval_map = {
        "5m": Client.KLINE_INTERVAL_5MINUTE,
        "15m": Client.KLINE_INTERVAL_15MINUTE,
    }
    if interval not in interval_map:
        raise ValueError(f"Unsupported Binance interval: {interval}")

    klines = binance_client.get_klines(
        symbol=BINANCE_SYMBOL,
        interval=interval_map[interval],
        limit=BINANCE_LIMIT,
    )
    if not klines:
        raise RuntimeError(f"No Binance data for {BINANCE_SYMBOL} {interval}")

    df = pd.DataFrame(
        klines,
        columns=[
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
            "ignore",
        ],
    )
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("timestamp")
    return normalize_ohlc(df)


def download_data(interval, period):
    if DATA_SOURCE == "binance":
        return download_data_binance(interval)
    return download_data_yfinance(interval, period)


def send_telegram_message(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(
        url,
        data={"chat_id": TELEGRAM_CHAT_ID, "text": message},
        timeout=10,
    )


def initialize_trades_csv():
    if os.path.exists(TRADES_CSV_FILE):
        return
    with open(TRADES_CSV_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
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
                "net_pnl",
            ]
        )


def log_trade_to_csv(
    timestamp,
    symbol,
    side,
    entry_price,
    sl,
    tp,
    exit_price,
    exit_reason,
    qty,
    gross_pnl,
    fees_slippage,
    net_pnl,
):
    with open(TRADES_CSV_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                timestamp,
                symbol,
                side,
                f"{entry_price:.5f}",
                f"{sl:.5f}",
                f"{tp:.5f}",
                f"{exit_price:.5f}",
                exit_reason,
                f"{qty:.2f}",
                f"{gross_pnl:.2f}",
                f"{fees_slippage:.2f}",
                f"{net_pnl:.2f}",
            ]
        )


def session_name(local_time):
    if dt_time(20, 0) <= local_time or local_time < dt_time(0, 0):
        return "asian"
    if dt_time(3, 0) <= local_time < dt_time(8, 0):
        return "london"
    if dt_time(8, 0) <= local_time < dt_time(12, 0):
        return "new_york"
    return "off"


def find_pivots(df, strength=2):
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    pivot_high = np.full(len(df), np.nan)
    pivot_low = np.full(len(df), np.nan)

    for i in range(strength, len(df) - strength):
        high_window = highs[i - strength:i + strength + 1]
        low_window = lows[i - strength:i + strength + 1]
        if highs[i] == high_window.max() and high_window.argmax() == strength:
            pivot_high[i] = highs[i]
        if lows[i] == low_window.min() and low_window.argmin() == strength:
            pivot_low[i] = lows[i]

    df = df.copy()
    df["pivot_high"] = pivot_high
    df["pivot_low"] = pivot_low
    return df


def build_context():
    df_15m = download_data(SLOW_INTERVAL, LOOKBACK_PERIOD)
    df_5m = download_data(FAST_INTERVAL, LOOKBACK_PERIOD)

    # 15m structure and liquidity.
    slow = df_15m.copy()
    slow["ema20"] = ema(slow["close"], 20)
    slow["ema50"] = ema(slow["close"], 50)
    slow["ema20_slope"] = slow["ema20"].diff()
    slow["rsi14"] = rsi(slow["close"], 14)
    slow["atr14"] = atr(slow["high"], slow["low"], slow["close"], 14)
    slow = find_pivots(slow, strength=2)

    local_index = slow.index.tz_convert(NY)
    slow["local_date"] = local_index.date
    slow["local_time"] = local_index.time
    slow["session"] = slow["local_time"].apply(session_name)
    day_stats = (
        slow.groupby("local_date")[["high", "low"]]
        .agg(day_high=("high", "max"), day_low=("low", "min"))
        .shift(1)
    )

    last_pivot_low = np.nan
    last_pivot_high = np.nan
    leg_low = np.nan
    leg_high = np.nan
    fib_618 = np.nan
    fib_786 = np.nan
    records = []
    for _, row in slow.iterrows():
        if not np.isnan(row["pivot_low"]):
            last_pivot_low = row["pivot_low"]
            if not np.isnan(last_pivot_high) and last_pivot_high > last_pivot_low:
                leg_low = last_pivot_low
                leg_high = last_pivot_high
                fib_618 = leg_high - (leg_high - leg_low) * 0.618
                fib_786 = leg_high - (leg_high - leg_low) * 0.786

        if not np.isnan(row["pivot_high"]):
            last_pivot_high = row["pivot_high"]
            if not np.isnan(last_pivot_low) and last_pivot_high > last_pivot_low:
                leg_low = last_pivot_low
                leg_high = last_pivot_high
                fib_618 = leg_low + (leg_high - leg_low) * 0.618
                fib_786 = leg_low + (leg_high - leg_low) * 0.786

        records.append(
            {
                "trend_bullish": int(row["ema20"] > row["ema50"] and row["ema20_slope"] > 0),
                "trend_bearish": int(row["ema20"] < row["ema50"] and row["ema20_slope"] < 0),
                "leg_low": leg_low,
                "leg_high": leg_high,
                "fib_618": fib_618,
                "fib_786": fib_786,
                "day_high": day_stats.loc[row["local_date"], "day_high"] if row["local_date"] in day_stats.index else np.nan,
                "day_low": day_stats.loc[row["local_date"], "day_low"] if row["local_date"] in day_stats.index else np.nan,
            }
        )

    slow_ctx = pd.DataFrame(records, index=slow.index)
    slow = pd.concat([slow, slow_ctx], axis=1)

    # 5m confirmation.
    fast = df_5m.copy()
    fast["ema9"] = ema(fast["close"], 9)
    fast["ema21"] = ema(fast["close"], 21)
    fast["rsi14"] = rsi(fast["close"], 14)
    fast["bullish_impulse"] = (
        (fast["ema9"] > fast["ema21"])
        & (fast["close"] > fast["ema21"])
        & (fast["close"] > fast["open"])
        & (fast["rsi14"] >= 45)
    ).astype(int)
    fast["bearish_impulse"] = (
        (fast["ema9"] < fast["ema21"])
        & (fast["close"] < fast["ema21"])
        & (fast["close"] < fast["open"])
        & (fast["rsi14"] <= 55)
    ).astype(int)

    confirmation = fast.resample("15min", label="right", closed="right").agg(
        {
            "ema9": "last",
            "ema21": "last",
            "rsi14": "last",
            "bullish_impulse": "max",
            "bearish_impulse": "max",
        }
    )

    merged = pd.merge_asof(
        slow.sort_index(),
        confirmation.sort_index(),
        left_index=True,
        right_index=True,
        direction="backward",
        suffixes=("", "_5m"),
    )
    merged = merged.dropna(subset=["open", "high", "low", "close", "ema20", "ema50", "rsi14", "atr14", "ema9", "ema21", "rsi14_5m"])
    return merged


@dataclass
class PaperPosition:
    side: str
    entry: float
    sl: float
    tp: float
    qty: float
    opened_at: datetime


@dataclass
class BotState:
    daily_pnl_usd: float = 0.0
    daily_date: datetime.date = field(default_factory=lambda: datetime.now(UTC).date())
    trading_paused: bool = False
    daily_trade_entries: int = 0
    daily_trade_exits: int = 0
    daily_win_trades: int = 0
    daily_loss_trades: int = 0
    last_processed_close_time: int | None = None
    last_signal_time: datetime | None = None
    last_signal: str | None = None
    position: PaperPosition | None = None
    pending_direction: str | None = None
    pending_stop: float = np.nan
    pending_take_profit: float = np.nan
    pending_ttl: int = 0


def reset_daily_state_if_needed(state: BotState):
    today = datetime.now(UTC).date()
    if today == state.daily_date:
        return

    summary = (
        f"DAILY SUMMARY {state.daily_date} UTC\n"
        f"Net PnL: ${state.daily_pnl_usd:.2f}\n"
        f"Entries: {state.daily_trade_entries}\n"
        f"Exits: {state.daily_trade_exits}\n"
        f"Wins: {state.daily_win_trades}\n"
        f"Losses: {state.daily_loss_trades}\n"
        f"Open Positions: {1 if state.position else 0}\n"
        f"Paused: {state.trading_paused}"
    )
    print(summary)
    send_telegram_message(summary)

    state.daily_date = today
    state.daily_pnl_usd = 0.0
    state.trading_paused = False
    state.daily_trade_entries = 0
    state.daily_trade_exits = 0
    state.daily_win_trades = 0
    state.daily_loss_trades = 0
    print("New UTC day started. Daily PnL reset.")


def check_daily_guardrails(state: BotState):
    if state.trading_paused:
        return
    if state.daily_pnl_usd >= DAILY_TARGET_USD:
        state.trading_paused = True
        msg = f"Daily target hit: +${state.daily_pnl_usd:.2f}. Trading paused until next UTC day."
        print(msg)
        send_telegram_message(msg)
    elif state.daily_pnl_usd <= -DAILY_MAX_LOSS_USD:
        state.trading_paused = True
        msg = f"Daily max loss hit: ${state.daily_pnl_usd:.2f}. Trading paused until next UTC day."
        print(msg)
        send_telegram_message(msg)


def update_paper_position(state: BotState, current_price: float):
    symbol = instrument_symbol()
    position = state.position
    if not position:
        return

    exit_price = None
    exit_reason = None
    if position.side == "LONG":
        if current_price <= position.sl:
            exit_price = position.sl
            exit_reason = "SL"
        elif current_price >= position.tp:
            exit_price = position.tp
            exit_reason = "TP"
    else:
        if current_price >= position.sl:
            exit_price = position.sl
            exit_reason = "SL"
        elif current_price <= position.tp:
            exit_price = position.tp
            exit_reason = "TP"

    if exit_price is None:
        return

    gross_pnl = (exit_price - position.entry) * position.qty if position.side == "LONG" else (position.entry - exit_price) * position.qty
    notional_entry = abs(position.entry * position.qty)
    notional_exit = abs(exit_price * position.qty)
    fees = (notional_entry + notional_exit) * 0.001
    slippage = (notional_entry + notional_exit) * 0.0005
    net_pnl = gross_pnl - fees - slippage

    state.daily_pnl_usd += net_pnl
    state.daily_trade_exits += 1
    if net_pnl >= 0:
        state.daily_win_trades += 1
    else:
        state.daily_loss_trades += 1

    msg = (
        f"PAPER EXIT {symbol} {position.side} {exit_reason} "
        f"Gross=${gross_pnl:.2f} Fees+Slip=${fees + slippage:.2f} "
        f"NetPnL=${net_pnl:.2f} DailyPnL=${state.daily_pnl_usd:.2f}"
    )
    print(msg)
    send_telegram_message(msg)
    log_trade_to_csv(
        timestamp=datetime.now(UTC).isoformat(),
        symbol=symbol,
        side=position.side,
        entry_price=position.entry,
        sl=position.sl,
        tp=position.tp,
        exit_price=exit_price,
        exit_reason=exit_reason,
        qty=position.qty,
        gross_pnl=gross_pnl,
        fees_slippage=fees + slippage,
        net_pnl=net_pnl,
    )
    state.position = None
    check_daily_guardrails(state)


def scan_market(state: BotState, df: pd.DataFrame):
    symbol = instrument_symbol()
    latest = df.iloc[-1]
    latest_close_time = int(latest.name.value // 10**9)
    if state.last_processed_close_time == latest_close_time:
        return
    state.last_processed_close_time = latest_close_time

    update_paper_position(state, latest["close"])

    if state.trading_paused or state.position:
        return

    if state.pending_ttl > 0:
        state.pending_ttl -= 1
        if state.pending_ttl == 0:
            state.pending_direction = None
            state.pending_stop = np.nan
            state.pending_take_profit = np.nan

    price = latest["close"]
    open_ = latest["open"]
    high = latest["high"]
    low = latest["low"]
    atr_value = latest["atr14"]
    rsi_value = latest["rsi14"]
    trend_bullish = bool(latest["trend_bullish"])
    trend_bearish = bool(latest["trend_bearish"])
    fib_618 = latest["fib_618"]
    fib_786 = latest["fib_786"]
    leg_low = latest["leg_low"]
    leg_high = latest["leg_high"]
    day_low = latest["day_low"]
    day_high = latest["day_high"]
    ema9 = latest["ema9"]
    ema21 = latest["ema21"]
    rsi14_5m = latest["rsi14_5m"]
    bullish_impulse = bool(latest["bullish_impulse"])
    bearish_impulse = bool(latest["bearish_impulse"])

    if np.isnan(atr_value) or np.isnan(rsi_value) or np.isnan(ema9) or np.isnan(ema21) or np.isnan(rsi14_5m):
        return

    if np.isnan(leg_low) or np.isnan(leg_high) or leg_high <= leg_low:
        return

    bullish_5m_score = int(bullish_impulse) + int(ema9 > ema21) + int(rsi14_5m >= 45)
    bearish_5m_score = int(bearish_impulse) + int(ema9 < ema21) + int(rsi14_5m <= 55)
    bullish_5m_confirmation = bullish_5m_score >= 1
    bearish_5m_confirmation = bearish_5m_score >= 1

    sweep_below_day = not np.isnan(day_low) and low < day_low
    sweep_above_day = not np.isnan(day_high) and high > day_high

    bullish_setup = (
        trend_bullish
        and sweep_below_day
        and not np.isnan(fib_618)
        and not np.isnan(fib_786)
        and low <= fib_618
        and high >= fib_786
        and price > fib_618
        and rsi_value >= 40
    )

    bearish_setup = (
        trend_bearish
        and sweep_above_day
        and not np.isnan(fib_618)
        and not np.isnan(fib_786)
        and low <= fib_786
        and high >= fib_618
        and price < fib_618
        and rsi_value <= 60
    )

    if bullish_setup:
        state.pending_direction = "LONG"
        state.pending_stop = min(low, day_low if not np.isnan(day_low) else low, leg_low) - atr_value * ATR_BUFFER
        risk = price - state.pending_stop
        if risk > 0:
            state.pending_take_profit = price + risk * RR_RATIO
            state.pending_ttl = 4

    elif bearish_setup:
        state.pending_direction = "SHORT"
        state.pending_stop = max(high, day_high if not np.isnan(day_high) else high, leg_high) + atr_value * ATR_BUFFER
        risk = state.pending_stop - price
        if risk > 0:
            state.pending_take_profit = price - risk * RR_RATIO
            state.pending_ttl = 4

    if state.pending_direction == "LONG" and bullish_5m_confirmation:
        risk = price - state.pending_stop
        if risk > 0:
            qty = max(1, RISK_PER_TRADE_USD / risk)
            state.position = PaperPosition(
                side="LONG",
                entry=price,
                sl=state.pending_stop,
                tp=state.pending_take_profit,
                qty=qty,
                opened_at=datetime.now(UTC),
            )
            state.daily_trade_entries += 1
            state.last_signal = "LONG"
            state.last_signal_time = datetime.now(UTC)
            msg = f"PAPER ENTRY {symbol} LONG Entry={price:.5f} SL={state.pending_stop:.5f} TP={state.pending_take_profit:.5f} Qty={qty:.2f}"
            print(msg)
            send_telegram_message(msg)
        state.pending_direction = None
        state.pending_stop = np.nan
        state.pending_take_profit = np.nan
        state.pending_ttl = 0

    elif state.pending_direction == "SHORT" and bearish_5m_confirmation:
        risk = state.pending_stop - price
        if risk > 0:
            qty = max(1, RISK_PER_TRADE_USD / risk)
            state.position = PaperPosition(
                side="SHORT",
                entry=price,
                sl=state.pending_stop,
                tp=state.pending_take_profit,
                qty=qty,
                opened_at=datetime.now(UTC),
            )
            state.daily_trade_entries += 1
            state.last_signal = "SHORT"
            state.last_signal_time = datetime.now(UTC)
            msg = f"PAPER ENTRY {symbol} SHORT Entry={price:.5f} SL={state.pending_stop:.5f} TP={state.pending_take_profit:.5f} Qty={qty:.2f}"
            print(msg)
            send_telegram_message(msg)
        state.pending_direction = None
        state.pending_stop = np.nan
        state.pending_take_profit = np.nan
        state.pending_ttl = 0


def main():
    initialize_trades_csv()
    state = BotState()
    print(
        f"EUR/USD paper bot started | source={DATA_SOURCE} symbol={instrument_symbol()} "
        f"interval={FAST_INTERVAL}/{SLOW_INTERVAL} paper={PAPER_TRADING}"
    )

    while True:
        try:
            reset_daily_state_if_needed(state)
            df = build_context()
            print(
                f"[{datetime.now(UTC).isoformat()}] EUR/USD scan | bars={len(df)} "
                f"open_position={bool(state.position)} pending={state.pending_direction} "
                f"daily_pnl=${state.daily_pnl_usd:.2f} paused={state.trading_paused}"
            )
            scan_market(state, df)
        except Exception as exc:
            print(f"EUR/USD bot error: {exc}")
            send_telegram_message(f"EUR/USD bot error: {exc}")

        time.sleep(SCAN_SECONDS)


if __name__ == "__main__":
    main()