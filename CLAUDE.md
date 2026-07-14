# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project

Automated crypto trading bot. **Sole focus: trading BTC/USDT on Binance.**
The EUR/USD "Simon" strategy was removed on 2026-07-14 — do not reintroduce it.

**Goal:** a paper-proven, positive-expectancy BTC strategy. The user's stated
target is $20/day on a ~$1,000 account (≈2%/day). Treat this as aspirational —
see "Reality check" below. Prove a real edge and consistency first, scale later.

## Current state (2026-07-14)

- Live bot runs in **PAPER_TRADING** mode. Not live yet.
- 1.5 months of paper trading produced only **3 trades, +$7.23 net total**
  (~$0.16/day). The binding constraint is **trade frequency**, not win rate
  (win rate so far is 2/3) or R:R.
- **Known gap:** the live bot trades **5m candles with a 1h trend filter**, but
  the only backtest ([backtest.py](backtest.py)) runs on **1h candles with no
  1h filter**. They are different strategies — the backtest does not predict
  live behavior. Closing this gap is the top priority.

## Key files

- [main.py](main.py) — live/paper bot. Scans BTCUSDT 5m + 1h every 60s.
  EMA9/EMA21 + RSI(14) + ATR(14) trend-following. 1h EMA trend must align.
  ATR-based SL (1.5×ATR), fixed R:R take-profit. Fixed USD risk per trade.
  Daily target/max-loss guardrails. Logs closed trades to `trades.csv`.
- [backtest.py](backtest.py) — 1h backtest with walk-forward. **Does not match
  the live 5m logic** (see gap above).
- `trades.csv` — closed paper trades log.
- `BTCUSDT_1h.csv` — historical 1h data used by the backtest.
- `scripts/` — `botctl.sh` + start/stop wrappers (BTC-only after cleanup).

## Strategy parameters (in main.py)

Risk $2.50/trade, R:R 2.5, ATR%_min 0.5, LONG RSI 50–70, SHORT RSI 20–60,
30-min cooldown, daily target $8 / max loss $10. One open position at a time.

## Reality check (keep the user honest)

- $20/day on $1,000 = ~730%/year compounded. Not sustainable for any real
  strategy. Reset expectations toward ~$2–5/day proven over 100+ trades first.
- Paper fills are optimistic (exact SL/TP, no wick-through/spread). Live is worse.
- Only two honest levers for more profit: **trade more often** or **risk more
  per trade**. On a single symbol, frequency comes from looser entries — which
  must be validated in a *matching* backtest before going live.

## Roadmap

1. Housekeeping: strip EUR/USD from `scripts/`.
2. `scripts/fetch_data.py`: pull real BTCUSDT 5m + 1h klines from Binance.
3. A 5m backtest that mirrors [main.py](main.py) exactly (entries, 1h filter,
   SL/TP, fees) → measure real win rate, frequency, profit factor.
4. Tune entry filters from that evidence (frequency vs. profit factor).
5. Set realistic sizing/target. Only then consider going live.

## Conventions

- Never commit or push unless the user asks.
- `.env` holds `BINANCE_API_KEY`/`BINANCE_API_SECRET` + Telegram creds. Never
  print or commit secrets.
- Public Binance klines endpoints need no API keys — use them for backtesting data.
