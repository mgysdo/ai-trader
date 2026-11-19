"""Read-only Telegram command bot for checking BTC + your Binance position.

Answers ONLY your own chat (TELEGRAM_CHAT_ID from .env); ignores everyone else.
Deliberately has NO trading commands — it can't place, change or cancel orders.

Commands: /status  /orders  /check  /levels  /help

    ./venv/bin/python scripts/telegram_bot.py
    ./venv/bin/python scripts/telegram_bot.py --entry 64384.93   # entry for P&L maths
"""
import argparse
import os
import sys
import time

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from main import (  # noqa: E402
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    _binance_public_get,
    _binance_signed_request,
)
from watch_bullish import check, klines  # noqa: E402

API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
FEE = 0.00075  # spot fee per side with BNB


def price():
    return float(_binance_public_get("/api/v3/ticker/price", {"symbol": "BTCUSDT"})["price"])


def balances():
    acct = _binance_signed_request("GET", "/api/v3/account")
    out = {}
    for b in acct["balances"]:
        tot = float(b["free"]) + float(b["locked"])
        if tot > 0:
            out[b["asset"]] = (float(b["free"]), float(b["locked"]))
    return out


def open_orders():
    return _binance_signed_request("GET", "/api/v3/openOrders", {"symbol": "BTCUSDT"})


def cmd_status(entry):
    p = price()
    bal = balances()
    btc = sum(bal.get("BTC", (0, 0)))
    usdt = sum(bal.get("USDT", (0, 0)))
    lines = [f"BTC ${p:,.2f}", f"Holdings: {btc:.6f} BTC, {usdt:.2f} USDT"]
    if btc > 0:
        be = entry * (1 + FEE) / (1 - FEE)
        net = btc * p * (1 - FEE) - btc * entry * (1 + FEE)
        lines.append(f"Entry {entry:,.2f} | break-even {be:,.0f} | net P&L ≈ {net:+.2f} USD")
        for o in open_orders():
            lvl = float(o["stopPrice"]) or float(o["price"])
            lines.append(f"{o['type']} @ {lvl:,.0f} → {lvl / p - 1:+.1%} away")
    return "\n".join(lines)


def cmd_orders():
    oo = open_orders()
    if not oo:
        return "No open BTCUSDT orders."
    rows = []
    for o in oo:
        stop = float(o["stopPrice"])
        rows.append(f"{o['side']} {o['type']} {float(o['origQty']):g} BTC @ {float(o['price']):,.2f}"
                    + (f" (trigger {stop:,.2f})" if stop else "") + f" — {o['status']}")
    return "\n".join(rows)


def cmd_check(reclaim, support):
    c, conds, ctx, broke = check(reclaim, support)
    lines = [f"1h close {c:,.0f}"] + [f"{'✅' if v else '❌'} {k}" for k, v in conds.items()] + [ctx]
    lines.append("🟢 ALL MET" if all(conds.values()) else f"{sum(conds.values())}/3 met — no signal yet")
    if broke:
        lines.append(f"🔴 below key support {support:,.0f}")
    return "\n".join(lines)


def cmd_levels():
    p = price()
    h1 = klines("1h", 170)
    d1 = klines("1d", 110)
    sma100 = d1.c.rolling(100).mean().iloc[-1]
    rows = [f"BTC ${p:,.0f}"]
    for label, n in [("24h", 24), ("48h", 48), ("7d", 168)]:
        rows.append(f"{label}: high {h1.h.tail(n).max():,.0f} / low {h1.l.tail(n).min():,.0f}")
    rows.append(f"1h EMA50 {h1.c.ewm(span=50).mean().iloc[-1]:,.0f}")
    rows.append(f"Daily SMA100 {sma100:,.0f} | allocator BUY above {sma100 * 1.02:,.0f}")
    return "\n".join(rows)


HELP = ("Read-only commands:\n/status – price, holdings, P&L, distance to orders\n"
        "/orders – open BTCUSDT orders\n/check – bullish checklist (1h)\n"
        "/levels – key highs/lows, EMA, allocator trigger\n(no trading commands by design)")


def send(text):
    for attempt in range(3):
        try:
            r = requests.post(f"{API}/sendMessage",
                              data={"chat_id": TELEGRAM_CHAT_ID, "text": text[:4000]}, timeout=10).json()
            if r.get("ok"):
                return True
            print(f"send failed: {r.get('description')}", flush=True)
        except Exception as e:
            print(f"send error: {e}", flush=True)
        time.sleep(2)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entry", type=float, default=64384.93)
    ap.add_argument("--reclaim", type=float, default=64000)
    ap.add_argument("--support", type=float, default=62006)
    a = ap.parse_args()
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        sys.exit("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing from .env")

    # Skip anything sent before startup.
    upd = requests.get(f"{API}/getUpdates", params={"timeout": 0}, timeout=15).json()
    if not upd.get("ok"):
        sys.exit(f"getUpdates failed: {upd.get('description')}")
    offset = (upd["result"][-1]["update_id"] + 1) if upd["result"] else None
    send("🤖 Command bot online. Send /help")
    print("bot online", flush=True)

    handlers = {
        "/status": lambda: cmd_status(a.entry),
        "/orders": cmd_orders,
        "/check": lambda: cmd_check(a.reclaim, a.support),
        "/levels": cmd_levels,
        "/help": lambda: HELP,
        "/start": lambda: HELP,
    }
    while True:
        try:
            r = requests.get(f"{API}/getUpdates", params={"timeout": 50, "offset": offset}, timeout=60).json()
            for u in r.get("result", []):
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                if str(msg.get("chat", {}).get("id")) != str(TELEGRAM_CHAT_ID):
                    continue  # only answer the owner
                cmd = (msg.get("text") or "").strip().split()[0].split("@")[0].lower() if msg.get("text") else ""
                fn = handlers.get(cmd)
                try:
                    reply = fn() if fn else "Unknown command. " + HELP
                except Exception as e:
                    reply = f"Error: {e}"
                ok = send(reply)
                print(f"{time.strftime('%H:%M:%S')} {cmd} → {'sent' if ok else 'SEND FAILED'}", flush=True)
        except Exception as e:
            print(f"poll error: {e}", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
