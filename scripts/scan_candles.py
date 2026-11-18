"""Scan recent candles for classic candlestick patterns, with trend context.

Read-only (public Binance data, no keys). For chart *reading*, not signals:
tested 2026-11-18 on BTC+ETH 1d/4h/1h (24 patterns) — almost all ≈ coin-flip.
Only "Three white soldiers" on DAILY showed a consistent edge (trend continuation).

    ./venv/bin/python scripts/scan_candles.py               # BTCUSDT
    ./venv/bin/python scripts/scan_candles.py ETHUSDT --bars 15
"""
import argparse
import numpy as np
import pandas as pd
import requests

# Historical edge from the 2026-11-18 test (BTC+ETH, next 3 candles, after fees ignored).
RELIABILITY = {"Three white soldiers": "some edge on DAILY (trend continuation)"}


def klines(sym, iv, limit=300):
    r = requests.get("https://api.binance.com/api/v3/klines",
                     params={"symbol": sym, "interval": iv, "limit": limit}, timeout=15).json()
    d = pd.DataFrame(r).iloc[:, [0, 1, 2, 3, 4]].astype(float)
    d.columns = ["t", "o", "h", "l", "c"]
    d["t"] = pd.to_datetime(d.t, unit="ms")
    return d.iloc[:-1].reset_index(drop=True)  # completed candles only


def patterns(d):
    o,h,l,c=d.o,d.h,d.l,d.c; body=(c-o).abs(); rng=(h-l).replace(0,np.nan)
    up=h-np.maximum(o,c); lo=np.minimum(o,c)-l; g=c>o; r=c<o
    avgb=body.rolling(20).mean()
    down=c.shift(1)<c.shift(6); upt=c.shift(1)>c.shift(6)   # prior 5-bar trend
    S=lambda k:k.shift(1); S2=lambda k:k.shift(2)
    P={}
    P["Hammer (after down)"]=(lo>=2*body)&(up<=0.3*body+1e-9)&(body/rng>0.1)&down,+1
    P["Inverted hammer (after down)"]=(up>=2*body)&(lo<=0.3*body+1e-9)&(body/rng>0.1)&down,+1
    P["Dragonfly doji (after down)"]=(body/rng<0.1)&(lo/rng>0.7)&down,+1
    P["Hanging man (after up)"]=(lo>=2*body)&(up<=0.3*body+1e-9)&(body/rng>0.1)&upt,-1
    P["Shooting star (after up)"]=(up>=2*body)&(lo<=0.3*body+1e-9)&(body/rng>0.1)&upt,-1
    P["Gravestone doji (after up)"]=(body/rng<0.1)&(up/rng>0.7)&upt,-1
    P["Bullish marubozu"]=g&(body/rng>0.9)&(body>avgb),+1
    P["Bearish marubozu"]=r&(body/rng>0.9)&(body>avgb),-1
    P["Bullish engulfing"]=S(r)&g&(o<=S(c))&(c>=S(o))&(body>S(body))&down,+1
    P["Bearish engulfing"]=S(g)&r&(o>=S(c))&(c<=S(o))&(body>S(body))&upt,-1
    P["Piercing line"]=S(r)&g&(o<S(c))&(c>(S(o)+S(c))/2)&(c<S(o))&down,+1
    P["Dark cloud cover"]=S(g)&r&(o>S(c))&(c<(S(o)+S(c))/2)&(c>S(o))&upt,-1
    P["Bullish harami"]=S(r)&g&(S(body)>avgb)&(o>S(c))&(c<S(o))&down,+1
    P["Bearish harami"]=S(g)&r&(S(body)>avgb)&(o<S(c))&(c>S(o))&upt,-1
    P["Tweezer bottom"]=S(r)&g&((l-S(l)).abs()<0.001*c)&down,+1
    P["Tweezer top"]=S(g)&r&((h-S(h)).abs()<0.001*c)&upt,-1
    P["Morning star"]=S2(r)&(S2(body)>avgb)&(S(body)<0.3*S2(body))&g&(c>(S2(o)+S2(c))/2)&c.shift(3).gt(c.shift(8)).eq(False),+1
    P["Evening star"]=S2(g)&(S2(body)>avgb)&(S(body)<0.3*S2(body))&r&(c<(S2(o)+S2(c))/2)&c.shift(3).gt(c.shift(8)),-1
    P["Three white soldiers"]=g&S(g)&S2(g)&(c>S(c))&(S(c)>S2(c))&(body>0.5*avgb)&(S(body)>0.5*avgb)&(S2(body)>0.5*avgb),+1
    P["Three black crows"]=r&S(r)&S2(r)&(c<S(c))&(S(c)<S2(c))&(body>0.5*avgb)&(S(body)>0.5*avgb)&(S2(body)>0.5*avgb),-1
    hb=S2(r)&S(g)&(S(o)>S2(c))&(S(c)<S2(o)); P["Three inside up"]=hb&g&(c>S2(o)),+1
    hs=S2(g)&S(r)&(S(o)<S2(c))&(S(c)>S2(o)); P["Three inside down"]=hs&r&(c<S2(o)),-1
    eb=S2(r)&S(g)&(S(o)<=S2(c))&(S(c)>=S2(o)); P["Three outside up"]=eb&g&(c>S(c)),+1
    es=S2(g)&S(r)&(S(o)>=S2(c))&(S(c)<=S2(o)); P["Three outside down"]=es&r&(c<S(c)),-1
    return P

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol", nargs="?", default="BTCUSDT")
    ap.add_argument("--bars", type=int, default=10, help="how many recent candles to scan")
    a = ap.parse_args()
    for iv in ["1d", "4h", "1h"]:
        d = klines(a.symbol, iv)
        c = d.c.iloc[-1]
        s20, s50, s100 = (d.c.rolling(n).mean().iloc[-1] for n in (20, 50, 100))
        trend = "UP" if c > s50 > s100 else "DOWN" if c < s50 < s100 else "MIXED"
        print(f"\n== {a.symbol} {iv} | close {c:,.2f} | SMA20 {s20:,.0f} SMA50 {s50:,.0f} "
              f"SMA100 {s100:,.0f} | trend {trend}")
        hits = []
        for nm, (m, dirn) in patterns(d).items():
            for i in np.where(m.fillna(False).values)[0]:
                if i >= len(d) - a.bars:
                    hits.append((d.t[i], nm, dirn))
        if not hits:
            print("  no patterns in the last", a.bars, "candles")
        for t, nm, dirn in sorted(hits):
            note = RELIABILITY.get(nm, "historically ≈ coin-flip — context only")
            print(f"  {t:%Y-%m-%d %H:%M}  {'▲ bullish' if dirn > 0 else '▼ bearish'}  {nm:30s} [{note}]")


if __name__ == "__main__":
    main()
