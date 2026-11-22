"""Watch BTC for a confirmed 4h trend turn and ping Telegram. Read-only, never trades.

Signal = ALL of, on the last COMPLETED 4h candle:
  1. 4h close > 4h EMA20
  2. 4h RSI(14) > 50
  3. 4h higher low: latest 4h swing low > the previous swing low
Why 4h, not 1h: on 2026-11-19 a 1h-only checklist (reclaim 64k, RSI>50, 1h higher
low) fired at 64,038 while the 4h was still below its EMA20 — that was the exact
top; BTC fell −14% to 55,130 over the next 40h. Lower-timeframe signals against the
higher-timeframe trend are relief rallies, not reversals.

Also reports 1h context. Sends a one-off warning if a 1h candle closes below key
support (default 55,130 = the 2026-11-21 crash low). Exits after the bullish ping.

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

SUPPORT = 55130


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


def check(support=SUPPORT):
    h1, h4 = klines("1h"), klines("4h")
    c4 = h4.c.iloc[-1]
    e20 = h4.c.ewm(span=20).mean().iloc[-1]
    r4 = rsi(h4.c).iloc[-1]
    sl = swing_lows(h4, w=2)
    hl = len(sl) >= 2 and sl[-1] > sl[-2]
    conds = {
        f"4h close > EMA20 ({e20:,.0f})": c4 > e20,
        f"4h RSI > 50 (now {r4:.0f})": r4 > 50,
        f"4h higher low ({sl[-2]:,.0f} → {sl[-1]:,.0f})" if len(sl) >= 2 else "4h higher low": hl,
    }
    c1 = h1.c.iloc[-1]
    ctx = (f"1h close {c1:,.0f}, 1h RSI {rsi(h1.c).iloc[-1]:.0f}, "
           f"1h EMA50 {h1.c.ewm(span=50).mean().iloc[-1]:,.0f}")
    return c4, conds, ctx, c1 < support


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--support", type=float, default=SUPPORT)
    ap.add_argument("--every", type=int, default=300, help="seconds between checks")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--no-telegram", action="store_true",
                    help="don't message Telegram; exit on signal OR support break "
                         "(exit = the alert, e.g. for a Claude Code background task)")
    a = ap.parse_args()
    notify = (lambda m: None) if a.no_telegram else send_telegram
    warned = False
    while True:
        try:
            c, conds, ctx, broke = check(a.support)
            lines = [f"{'✅' if v else '❌'} {k}" for k, v in conds.items()]
            stamp = time.strftime("%Y-%m-%d %H:%M")
            print(f"[{stamp}] BTC 4h close {c:,.0f} | " + " | ".join(lines) + f" | {ctx}", flush=True)
            if a.once:
                return
            if all(conds.values()):
                msg = ("🟢 BTC 4h trend-turn checklist MET\n" + "\n".join(lines) + f"\n{ctx}\n"
                       "Not a tested edge — confirm on the chart, set isolated margin + stop before entering. "
                       "Allocator (daily SMA100+2%) still decides the real position.")
                notify(msg)
                print("SIGNAL 🟢 — exiting.", flush=True)
                return
            if broke and not warned:
                notify(f"🔴 BTC 1h closed below the crash low {a.support:,.0f}. "
                       "Downtrend continuing — no bullish signal.")
                print(f"WARNING 🔴 — 1h close below {a.support:,.0f}.", flush=True)
                if a.no_telegram:
                    return
                warned = True
        except Exception as e:  # network hiccup: log and keep watching
            print(f"check failed: {e}", flush=True)
        time.sleep(a.every)


if __name__ == "__main__":
    main()
