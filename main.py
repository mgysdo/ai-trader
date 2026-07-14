"""BTC daily trend allocator — the production strategy (see CLAUDE.md).

Long BTC when the daily close is above SMA(100) * 1.02, fully in USDT when it
falls below SMA(100) * 0.98 (hysteresis band cuts whipsaws in half; validated
on 9 years of data in trend_daily.py + the band test).

Spot-only, long-or-cash, no leverage, no shorting. Acts at most once per UTC
day, on the completed daily candle. Paper mode simulates fills at the daily
close with commission + slippage; state survives restarts via a JSON file.

    ./venv/bin/python main.py           # continuous (checks hourly)
    ./venv/bin/python main.py --once    # single check, then exit (cron/test)

Live trading is intentionally NOT implemented yet — paper burn-in first.
"""

import csv
import json
import os
import sys
import time
from datetime import UTC, datetime

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

# ---- Strategy (validated 2026-07-14, see CLAUDE.md) -----------------------
SMA_LEN = 100
BAND = 0.02                  # enter > SMA*(1+BAND), exit < SMA*(1-BAND)
SYMBOL = "BTCUSDT"

# ---- Account / execution ---------------------------------------------------
PAPER_TRADING = True
START_USDT = 200.0
COMMISSION_RATE = 0.001
SLIPPAGE_RATE = 0.0005

CHECK_INTERVAL_SEC = 3600    # re-check hourly; acts only on a new daily close

STATE_FILE = "allocator_state.json"
TRADES_FILE = "allocator_trades.csv"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

KLINES_URL = "https://api.binance.com/api/v3/klines"


def log(msg):
    print(f"[{datetime.now(UTC).isoformat(timespec='seconds')}] {msg}", flush=True)


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": message},
            timeout=10,
        )
    except requests.RequestException as e:
        log(f"Telegram error: {e}")


# ---- State -----------------------------------------------------------------
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        "position": "USDT",          # "USDT" (flat) or "BTC" (long)
        "usdt": START_USDT,
        "btc_qty": 0.0,
        "last_processed_close": None,  # ISO time of last acted-on daily candle
        "entry_price": None,
    }


def save_state(state):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_FILE)


def init_trades_csv():
    if not os.path.exists(TRADES_FILE):
        with open(TRADES_FILE, "w", newline="") as f:
            csv.writer(f).writerow([
                "timestamp", "action", "price", "btc_qty", "usdt_value",
                "fee_usdt", "equity_after", "close", "sma", "reason",
            ])


def log_trade(action, price, qty, value, fee, equity, close, sma, reason):
    with open(TRADES_FILE, "a", newline="") as f:
        csv.writer(f).writerow([
            datetime.now(UTC).isoformat(), action, f"{price:.2f}",
            f"{qty:.8f}", f"{value:.2f}", f"{fee:.4f}", f"{equity:.2f}",
            f"{close:.2f}", f"{sma:.2f}", reason,
        ])


# ---- Data ------------------------------------------------------------------
def fetch_completed_daily(limit=SMA_LEN + 5):
    """Return DataFrame of COMPLETED daily candles (in-progress day dropped)."""
    resp = requests.get(
        KLINES_URL,
        params={"symbol": SYMBOL, "interval": "1d", "limit": limit},
        timeout=20,
    )
    resp.raise_for_status()
    rows = resp.json()

    df = pd.DataFrame(
        [(r[0], float(r[4]), r[6]) for r in rows],
        columns=["open_time", "close", "close_time"],
    )
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    df = df[df["close_time"] <= now_ms]          # completed candles only
    df["close_dt"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    return df.reset_index(drop=True)


# ---- Core ------------------------------------------------------------------
def check_and_act(state):
    df = fetch_completed_daily()
    if len(df) < SMA_LEN:
        log(f"Not enough daily candles ({len(df)}/{SMA_LEN}).")
        return

    last = df.iloc[-1]
    close = last["close"]
    close_iso = last["close_dt"].isoformat()
    sma = df["close"].tail(SMA_LEN).mean()
    upper, lower = sma * (1 + BAND), sma * (1 - BAND)

    equity = state["usdt"] + state["btc_qty"] * close
    log(
        f"close={close:.0f} sma{SMA_LEN}={sma:.0f} "
        f"band=[{lower:.0f},{upper:.0f}] pos={state['position']} "
        f"equity=${equity:.2f}"
    )

    if state["last_processed_close"] == close_iso:
        return  # Already acted on this daily candle.
    state["last_processed_close"] = close_iso

    action = None
    if state["position"] == "USDT" and close > upper:
        action = "BUY"
    elif state["position"] == "BTC" and close < lower:
        action = "SELL"

    if action is None:
        save_state(state)
        return

    if not PAPER_TRADING:
        raise NotImplementedError(
            "Live trading not implemented — finish the paper burn-in first."
        )

    if action == "BUY":
        fill = close * (1 + SLIPPAGE_RATE)
        spend = state["usdt"]
        fee = spend * COMMISSION_RATE
        qty = (spend - fee) / fill
        state.update(position="BTC", usdt=0.0, btc_qty=qty, entry_price=fill)
        equity = qty * close
        msg = (
            f"🟢 ALLOCATOR BUY (paper)\n{SYMBOL} @ ~{fill:.0f}\n"
            f"qty={qty:.8f}  fee=${fee:.2f}\n"
            f"close {close:.0f} > SMA{SMA_LEN}+{BAND:.0%} ({upper:.0f})\n"
            f"Equity: ${equity:.2f}"
        )
        log_trade("BUY", fill, qty, spend, fee, equity, close, sma,
                  f"close>{upper:.0f}")
    else:
        fill = close * (1 - SLIPPAGE_RATE)
        qty = state["btc_qty"]
        value = qty * fill
        fee = value * COMMISSION_RATE
        proceeds = value - fee
        pnl = (fill - (state["entry_price"] or fill)) * qty - fee
        state.update(position="USDT", usdt=proceeds, btc_qty=0.0,
                     entry_price=None)
        equity = proceeds
        msg = (
            f"🔴 ALLOCATOR SELL (paper)\n{SYMBOL} @ ~{fill:.0f}\n"
            f"qty={qty:.8f}  fee=${fee:.2f}  trade PnL=${pnl:+.2f}\n"
            f"close {close:.0f} < SMA{SMA_LEN}-{BAND:.0%} ({lower:.0f})\n"
            f"Equity: ${equity:.2f}"
        )
        log_trade("SELL", fill, qty, value, fee, equity, close, sma,
                  f"close<{lower:.0f}")

    save_state(state)
    log(msg.replace("\n", " | "))
    send_telegram(msg)


def main():
    once = "--once" in sys.argv
    init_trades_csv()
    state = load_state()
    log(
        f"Allocator started | SMA{SMA_LEN} band={BAND:.0%} "
        f"mode={'PAPER' if PAPER_TRADING else 'LIVE'} "
        f"pos={state['position']} usdt=${state['usdt']:.2f} "
        f"btc={state['btc_qty']:.8f}"
    )

    while True:
        try:
            check_and_act(state)
        except Exception as e:
            log(f"Error: {e}")
        if once:
            break
        time.sleep(CHECK_INTERVAL_SEC)


if __name__ == "__main__":
    main()
