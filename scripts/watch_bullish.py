"""Watch BTC for a confirmed bullish shift and ping Telegram. Read-only, never trades.

Signal = ALL of, on the last COMPLETED 1h candle:
  1. close > reclaim level (default 64,000 — the broken-support zone) and > 1h EMA50
  2. 1h RSI(14) > 50
  3. higher low: latest 1h swing low > the previous swing low
Also reports 4h context (close vs 4h EMA20). Sends a one-off warning if a 1h candle
closes below the key support (default 62,006). Exits after the bullish ping.

    ./venv/bin/python scripts/watch_bullish.py                 # loop, check every 5 min
    ./venv/bin/python scripts/watch_bullish.py --once          # single check, print status
"""
import argparse
import os
import sys
import time

import pandas as pd
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from main import send_telegram  # noqa: E402  (uses TELEGRAM_* from .env)


def klines(iv, n=200):
    r = requests.get("https://api.binance.com/api/v3/klines",
                     params={"symbol": "BTCUSDT", "interval": iv, "limit": n}, timeout=15).json()
    d = pd.DataFrame(r).iloc[:, :6].astype(float)
    d.columns = list("tohlcv")
    return d.iloc[:-1].reset_index(drop=True)  # completed candles only


def rsi(c, n=14):
    dl = c.diff()
    up = dl.clip(lower=0).ewm(alpha=1 / n).mean()
    dn = (-dl.clip(upper=0)).ewm(alpha=1 / n).mean()
    return 100 - 100 / (1 + up / dn)


def swing_lows(d, w=3):
    return [d.l[i] for i in range(w, len(d) - w) if d.l[i] == d.l[i - w:i + w + 1].min()]


def check(reclaim, support):
    h1, h4 = klines("1h"), klines("4h")
    c = h1.c.iloc[-1]
    e50 = h1.c.ewm(span=50).mean().iloc[-1]
    r = rsi(h1.c).iloc[-1]
    sl = swing_lows(h1)
    hl = len(sl) >= 2 and sl[-1] > sl[-2]
    e20_4h = h4.c.ewm(span=20).mean().iloc[-1]
    conds = {
        f"1h close > {reclaim:,.0f} & EMA50 ({e50:,.0f})": c > reclaim and c > e50,
        f"1h RSI > 50 (now {r:.0f})": r > 50,
        f"1h higher low ({sl[-2]:,.0f} → {sl[-1]:,.0f})" if len(sl) >= 2 else "1h higher low": hl,
    }
    ctx = f"4h close {h4.c.iloc[-1]:,.0f} vs 4h EMA20 {e20_4h:,.0f} ({'above ✅' if h4.c.iloc[-1] > e20_4h else 'below ❌'})"
    return c, conds, ctx, c < support


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reclaim", type=float, default=64000)
    ap.add_argument("--support", type=float, default=62006)
    ap.add_argument("--every", type=int, default=300, help="seconds between checks")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    warned = False
    while True:
        try:
            c, conds, ctx, broke = check(a.reclaim, a.support)
            lines = [f"{'✅' if v else '❌'} {k}" for k, v in conds.items()]
            stamp = time.strftime("%Y-%m-%d %H:%M")
            print(f"[{stamp}] BTC 1h close {c:,.0f} | " + " | ".join(lines) + f" | {ctx}", flush=True)
            if a.once:
                return
            if all(conds.values()):
                msg = ("🟢 BTC bullish checklist MET (1h)\n" + "\n".join(lines) + f"\n{ctx}\n"
                       "Not a tested edge — confirm on the chart, set isolated margin + stop before entering.")
                send_telegram(msg)
                print("SIGNAL — Telegram sent, exiting.", flush=True)
                return
            if broke and not warned:
                send_telegram(f"🔴 BTC 1h closed {c:,.0f}, below key support {a.support:,.0f}. "
                              "Downtrend continuing — no bullish signal. Spot OCO stop is at 61,378.")
                warned = True
        except Exception as e:  # network hiccup: log and keep watching
            print(f"check failed: {e}", flush=True)
        time.sleep(a.every)


if __name__ == "__main__":
    main()
