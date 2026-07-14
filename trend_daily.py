"""Daily trend allocator on 9 years of BTC (2017-2026): long above the N-day
SMA, cash below. Long-only, spot-realistic, no leverage, no shorting.

This is time-series momentum — the most robustly documented effect in the
trading literature. It trades a handful of times per year, so fees are
negligible, and its job is to capture bull legs and sit out crashes.

Costs: 0.1% commission + 0.05% slippage per side on every switch.
Signals act with a 1-day delay (signal on today's close, position from
tomorrow) — no lookahead.

    ./venv/bin/python trend_daily.py
"""

import numpy as np
import pandas as pd

COST_PER_SIDE = 0.0015
SMA_LENS = [50, 100, 150, 200]


def evaluate(close, sma_len):
    sma = close.rolling(sma_len).mean()
    signal = (close > sma).astype(int)
    pos = signal.shift(1).fillna(0)          # act next day
    ret = close.pct_change().fillna(0)

    switches = pos.diff().abs().fillna(0)    # 1 on each entry/exit
    strat_ret = pos * ret - switches * COST_PER_SIDE

    eq = (1 + strat_ret).cumprod()
    years = (close.index[-1] - close.index[0]).days / 365.25
    cagr = eq.iloc[-1] ** (1 / years) - 1
    dd = (eq / eq.cummax() - 1).min()

    monthly = (1 + strat_ret).resample("ME").prod() - 1
    return {
        "sma": sma_len,
        "total_x": eq.iloc[-1],
        "cagr_pct": cagr * 100,
        "max_dd_pct": dd * 100,
        "exposure_pct": pos.mean() * 100,
        "switches": int(switches.sum()),
        "avg_month_pct": monthly.mean() * 100,
        "pos_months_pct": (monthly > 0).mean() * 100,
        "_eq": eq, "_ret": strat_ret,
    }


def main():
    df = pd.read_csv("data/BTCUSDT_1d.csv", parse_dates=["timestamp"])
    close = df.set_index("timestamp")["close"]

    years = (close.index[-1] - close.index[0]).days / 365.25
    bh_eq = close / close.iloc[0]
    bh_cagr = bh_eq.iloc[-1] ** (1 / years) - 1
    bh_dd = (bh_eq / bh_eq.cummax() - 1).min()
    bh_monthly = (1 + close.pct_change().fillna(0)).resample("ME").prod() - 1

    print("\n" + "=" * 78)
    print("  DAILY TREND ALLOCATOR — BTC 2017-2026 (long above SMA, cash below)")
    print("=" * 78)
    print(f"\n  Buy & hold: {bh_eq.iloc[-1]:.1f}x | CAGR {bh_cagr * 100:.1f}% | "
          f"MaxDD {bh_dd * 100:.1f}% | avg month {bh_monthly.mean() * 100:+.2f}% | "
          f"months>0: {(bh_monthly > 0).mean() * 100:.0f}%")

    rows = []
    best = None
    for n in SMA_LENS:
        r = evaluate(close, n)
        rows.append({k: v for k, v in r.items() if not k.startswith("_")})
        if best is None or r["total_x"] > best["total_x"]:
            best = r

    res = pd.DataFrame(rows)
    print("\n" + res.round(2).to_string(index=False))

    # Year-by-year for the best SMA vs buy&hold.
    yr_s = (1 + best["_ret"]).resample("YE").prod() - 1
    yr_b = (1 + close.pct_change().fillna(0)).resample("YE").prod() - 1
    tbl = pd.DataFrame({
        "strategy_%": (yr_s * 100).round(1),
        "buy_hold_%": (yr_b * 100).round(1),
    })
    tbl.index = tbl.index.year
    print(f"\n  Year by year (SMA{best['sma']}):")
    print(tbl.to_string())

    print(f"\n  On $200: avg month = "
          f"${200 * best['avg_month_pct'] / 100:+.2f}, best-config CAGR "
          f"turns $200 into ${200 * (1 + best['cagr_pct'] / 100):,.0f} "
          f"in a typical year (lumpy, not linear).\n")


if __name__ == "__main__":
    main()
