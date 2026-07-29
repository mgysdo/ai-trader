"""BTC daily trend allocator — the production strategy (see CLAUDE.md).

Long BTC when the daily close is above SMA(100) * 1.02, fully in USDT when it
falls below SMA(100) * 0.98 (hysteresis band cuts whipsaws in half; validated
on 9 years of data in trend_daily.py + the band test).

Spot-only, long-or-cash, no leverage, no shorting. Acts at most once per UTC
day, on the completed daily candle. Paper mode simulates fills at the daily
close with commission + slippage; state survives restarts via a JSON file.

    ./venv/bin/python main.py             # continuous (checks hourly)
    ./venv/bin/python main.py --once      # single check, then exit (cron/test)
    ./venv/bin/python main.py --check-live  # test Binance API keys, no trading

Live mode (LIVE_TRADING=true in .env) sizes every order from the ACTUAL
Binance USDT/BTC balance at that moment — never from remembered amounts —
so monthly deposits (DCA) auto-deploy at the next signal with no code change.
Do not flip LIVE_TRADING on until: paper burn-in has passed, Binance API keys
have been rotated, and the key has trading enabled / withdrawals disabled /
IP-restricted. See CLAUDE.md "Agreed gates to live trading".
"""

import csv
import hashlib
import hmac
import json
import os
import sys
import time
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from urllib.parse import urlencode

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

# ---- Strategy (validated 2026-07-14, see CLAUDE.md) -----------------------
SMA_LEN = 100
BAND = 0.02                  # enter > SMA*(1+BAND), exit < SMA*(1-BAND)
SYMBOL = "BTCUSDT"

# ---- Account / execution ---------------------------------------------------
LIVE_TRADING = os.getenv("LIVE_TRADING", "false").strip().lower() == "true"
PAPER_TRADING = not LIVE_TRADING
START_USDT = 200.0
COMMISSION_RATE = 0.001      # paper-mode assumption; live fee is Binance's actual
SLIPPAGE_RATE = 0.0005

# Safety cap: refuse to auto-place an order above this notional and alert
# instead. Guards against a balance/config surprise silently trading a much
# larger amount than intended. Raise via .env as the DCA balance grows.
MAX_NOTIONAL_USD = float(os.getenv("BINANCE_MAX_NOTIONAL_USD", "5000"))

CHECK_INTERVAL_SEC = 3600    # re-check hourly; acts only on a new daily close

STATE_FILE = "allocator_state.json"
TRADES_FILE = "allocator_trades.csv"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

BINANCE_BASE_URL = "https://api.binance.com"
KLINES_URL = f"{BINANCE_BASE_URL}/api/v3/klines"
API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")
RECV_WINDOW_MS = 5000


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


# ---- Binance signed REST client (used only when LIVE_TRADING=true) --------
def _binance_signed_request(method, path, params=None):
    """Sign params with HMAC-SHA256 and send as a query string (per Binance
    docs, GET/POST/DELETE all read trade params from the query string, not
    the body)."""
    params = dict(params or {})
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = RECV_WINDOW_MS
    query = urlencode(params, doseq=True)
    signature = hmac.new(
        API_SECRET.encode(), query.encode(), hashlib.sha256
    ).hexdigest()
    url = f"{BINANCE_BASE_URL}{path}?{query}&signature={signature}"
    resp = requests.request(
        method, url, headers={"X-MBX-APIKEY": API_KEY}, timeout=15
    )
    resp.raise_for_status()
    return resp.json()


def _binance_public_get(path, params=None):
    resp = requests.get(f"{BINANCE_BASE_URL}{path}", params=params or {}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_free_balance(asset):
    account = _binance_signed_request("GET", "/api/v3/account")
    for b in account["balances"]:
        if b["asset"] == asset:
            return float(b["free"])
    return 0.0


def get_symbol_filters(symbol):
    info = _binance_public_get("/api/v3/exchangeInfo", {"symbol": symbol})
    filters = {f["filterType"]: f for f in info["symbols"][0]["filters"]}
    lot = filters.get("LOT_SIZE", {})
    notional = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL") or {}
    return {
        "step_size": Decimal(lot.get("stepSize", "0.00000001")),
        "min_notional": Decimal(notional.get("minNotional", "5")),
    }


def round_down_step(qty, step):
    """Floor qty to a multiple of step, matching step's decimal precision
    (required by Binance's LOT_SIZE filter — extra precision is rejected)."""
    qty = Decimal(str(qty))
    if step == 0:
        return qty
    steps = (qty / step).to_integral_value(rounding=ROUND_DOWN)
    return (steps * step).quantize(step)


def place_market_order(symbol, side, quantity=None, quote_order_qty=None):
    params = {"symbol": symbol, "side": side, "type": "MARKET"}
    if quantity is not None:
        params["quantity"] = quantity
    if quote_order_qty is not None:
        params["quoteOrderQty"] = quote_order_qty
    return _binance_signed_request("POST", "/api/v3/order", params)


def check_live_connection():
    if not API_KEY or not API_SECRET:
        print("BINANCE_API_KEY / BINANCE_API_SECRET not set in .env.")
        return
    usdt = get_free_balance("USDT")
    btc = get_free_balance("BTC")
    filt = get_symbol_filters(SYMBOL)
    print("Binance connectivity OK.")
    print(f"Free USDT: {usdt:.2f}")
    print(f"Free BTC : {btc:.8f}")
    print(f"{SYMBOL} filters: step_size={filt['step_size']} "
          f"min_notional={filt['min_notional']}")
    print("(No order was placed — this is a read-only check.)")


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

    # NOTE: state["last_processed_close"] is only persisted (save_state) once
    # the action below completes without raising. If a live order errors out,
    # nothing is saved, so the next hourly check retries the same candle
    # instead of silently skipping it.
    if action == "BUY":
        if PAPER_TRADING:
            fill = close * (1 + SLIPPAGE_RATE)
            spend = state["usdt"]
            fee = spend * COMMISSION_RATE
            qty = (spend - fee) / fill
        else:
            spend = get_free_balance("USDT")
            if spend > MAX_NOTIONAL_USD:
                raise RuntimeError(
                    f"USDT balance ${spend:.2f} exceeds safety cap "
                    f"${MAX_NOTIONAL_USD:.2f} — refusing to auto-trade. "
                    "Raise BINANCE_MAX_NOTIONAL_USD in .env if expected."
                )
            filt = get_symbol_filters(SYMBOL)
            if Decimal(str(spend)) < filt["min_notional"]:
                log(f"USDT balance ${spend:.2f} below min notional "
                    f"{filt['min_notional']} — skipping BUY this cycle.")
                return
            order = place_market_order(
                SYMBOL, "BUY", quote_order_qty=f"{spend:.2f}"
            )
            qty = float(order["executedQty"])       # already fee-net (BTC fee)
            spend = float(order["cummulativeQuoteQty"])
            fee = spend * COMMISSION_RATE            # informational only
            fill = spend / qty if qty else close

        state.update(position="BTC", usdt=0.0, btc_qty=qty, entry_price=fill)
        equity = qty * close
        msg = (
            f"🟢 ALLOCATOR BUY ({'paper' if PAPER_TRADING else 'LIVE'})\n"
            f"{SYMBOL} @ ~{fill:.0f}\nqty={qty:.8f}  spent=${spend:.2f}\n"
            f"close {close:.0f} > SMA{SMA_LEN}+{BAND:.0%} ({upper:.0f})\n"
            f"Equity: ${equity:.2f}"
        )
        log_trade("BUY", fill, qty, spend, fee, equity, close, sma,
                  f"close>{upper:.0f}")
    else:  # SELL
        if PAPER_TRADING:
            fill = close * (1 - SLIPPAGE_RATE)
            qty = state["btc_qty"]
            value = qty * fill
            fee = value * COMMISSION_RATE
            proceeds = value - fee
        else:
            qty_raw = get_free_balance("BTC")
            filt = get_symbol_filters(SYMBOL)
            qty_dec = round_down_step(qty_raw, filt["step_size"])
            if qty_dec <= 0 or (qty_dec * Decimal(str(close))) < filt["min_notional"]:
                log(f"BTC balance {qty_raw:.8f} below min notional — "
                    f"skipping SELL this cycle.")
                return
            order = place_market_order(
                SYMBOL, "SELL", quantity=format(qty_dec, "f")
            )
            qty = float(qty_dec)
            proceeds = float(order["cummulativeQuoteQty"])  # fee-net (USDT fee)
            fill = proceeds / qty if qty else close
            fee = proceeds * COMMISSION_RATE                # informational only

        pnl = (fill - (state["entry_price"] or fill)) * qty - fee
        state.update(position="USDT", usdt=proceeds, btc_qty=0.0,
                     entry_price=None)
        equity = proceeds
        msg = (
            f"🔴 ALLOCATOR SELL ({'paper' if PAPER_TRADING else 'LIVE'})\n"
            f"{SYMBOL} @ ~{fill:.0f}\nqty={qty:.8f}  proceeds=${proceeds:.2f}  "
            f"trade PnL=${pnl:+.2f}\n"
            f"close {close:.0f} < SMA{SMA_LEN}-{BAND:.0%} ({lower:.0f})\n"
            f"Equity: ${equity:.2f}"
        )
        log_trade("SELL", fill, qty, proceeds, fee, equity, close, sma,
                  f"close<{lower:.0f}")

    save_state(state)
    log(msg.replace("\n", " | "))
    send_telegram(msg)


def main():
    if "--check-live" in sys.argv:
        check_live_connection()
        return

    if LIVE_TRADING and (not API_KEY or not API_SECRET):
        raise SystemExit(
            "LIVE_TRADING=true but BINANCE_API_KEY/BINANCE_API_SECRET are "
            "not set in .env."
        )

    once = "--once" in sys.argv
    init_trades_csv()
    state = load_state()
    log(
        f"Allocator started | SMA{SMA_LEN} band={BAND:.0%} "
        f"mode={'LIVE' if LIVE_TRADING else 'PAPER'} "
        f"pos={state['position']} usdt=${state['usdt']:.2f} "
        f"btc={state['btc_qty']:.8f}"
    )

    while True:
        try:
            check_and_act(state)
        except Exception as e:
            log(f"Error: {e}")
            send_telegram(f"⚠️ Allocator error: {e}")
        if once:
            break
        time.sleep(CHECK_INTERVAL_SEC)


if __name__ == "__main__":
    main()
