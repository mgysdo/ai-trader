# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project

Automated BTC/USDT trading bot on Binance. **Production strategy: daily trend
allocator** — long BTC when the daily close > SMA(100)×1.02, fully in USDT
when close < SMA(100)×0.98. Spot only, long-or-cash, no leverage, no shorting.

User's long-term goal: $500–1k/month. That needs ~$30–60k capital at a
realistic 1–2%/month — the plan is: prove the engine on $200, add external
deposits over time. Do not entertain $/day targets on small capital.

## Files

- [main.py](main.py) — the allocator bot. Paper mode ($200 start). Checks
  hourly via public Binance REST, acts at most once per completed UTC daily
  candle. State: `allocator_state.json` (survives restarts). Trades:
  `allocator_trades.csv`. Telegram on switches. `--once` flag = single check
  (cron/testing). Live mode raises NotImplementedError until paper burn-in
  passes.
- [trend_daily.py](trend_daily.py) — self-contained 9-year validation of the
  strategy (keep; rerun after refetching data to re-verify).
- [scripts/fetch_data.py](scripts/fetch_data.py) — Binance public klines →
  `data/*.csv`. e.g. `--interval 1d --months 108`.
- `data/BTCUSDT_1d.csv` — daily history 2017→2026 used by trend_daily.py.
- `scripts/botctl.sh` — start|stop|restart|status|logs for the bot.
- venv rebuilt 2026-07-14 (Homebrew python3); deps: requests, pandas, numpy,
  python-dotenv only.

## Evidence for the strategy (validated 2026-07-14, 9y of data, 4 regimes)

All SMA lengths 50–200 beat buy&hold (14.6x, −83% DD): SMA50=61x/58.7% CAGR,
SMA100=22x/41.6%, SMA150=12x/−49% DD, SMA200=6.3x. Hysteresis bands 0–3%
tested: 2% halves switch count, keeps returns → chosen config SMA100+2%
(mid-plateau, not hindsight-best). Cuts every bear year (2018: −43% vs −73%;
2022: −50% vs −64%; 2026 YTD: −4.8% vs −28.5%). Expect ~2–4%/month **average**
but lumpy: only ~35–42% of months positive, historical drawdowns −50%+.
The #1 risk is abandoning the system mid-drawdown, not the code.

## Graveyard — tested and conclusively dead (2026-07-14). Do NOT revisit.

Intraday BTC on OHLC candles, 12 months of real 5m/1h data, 70/30 train/test:

| Archetype | Variants | Profitable OOS |
|---|---|---|
| EMA9/21+RSI momentum 5m (the original bot) | 72 | 0 (0 even in-sample) |
| Bollinger+RSI mean reversion 5m & 1h, long-only | 132 | 0 (0 even in-sample) |
| Donchian breakout 5m & 1h, futures fees, both sides | 24 | 0 (6 in-sample, all collapsed) |

Structural lessons: (1) gross edge of these signals ≈ zero — fees only made it
worse; (2) tight 5m stops + fixed-$ risk ⇒ large notional ⇒ ~0.15%/side costs
put every trade ~1R down; (3) the original bot's 3 paper trades (2 wins) were
pure noise — real win rate ~30%. Test window was a bear year (BTC −42%,
2025-07→2026-07); benchmark any long-only result against that.
Research scripts were removed in cleanup (results preserved above); old code
recoverable via git history. Old EUR/USD "Simon" strategy also removed.

## Pandas 3.0 gotcha

CSV-parsed datetimes may not be ns-resolution; `astype("int64")` then yields
NOT-nanoseconds and silently breaks epoch math. Convert via
`.values.astype("datetime64[ns]")` first.

## Deployment status (2026-07-14)

**Deployed and running** on the user's DigitalOcean droplet
(`ubuntu-s-1vcpu-2gb-sgp1`, Ubuntu 24.04, repo at `/root/ai-trader`) as
systemd service `ai-trader` (enabled = survives reboots, Restart=always).
Runbook: [DEPLOY.md](DEPLOY.md). First check confirmed correct behavior:
close 62,335 < buy trigger 72,130 → flat in USDT, $200 paper equity.
The old nohup/PID bots on the droplet were already dead (stale PID files) —
that silent-death fragility is why systemd is required.

**Paper burn-in started 2026-07-14, runs ~2–4 weeks.** Success = uptime and
correct mechanics (hourly heartbeats in `journalctl -u ai-trader`, reboot
survival, correct switch + Telegram alert if a band crossing happens) — NOT
P&L. Zero trades during burn-in is a PASS (BTC is far below the entry band).

## Agreed gates to live trading (in order)

1. Clean burn-in uptime record (~2–4 weeks from 2026-07-14).
2. Implement live order path: python-binance, market orders, min-notional
   (~$5 spot) checks; live mode currently raises NotImplementedError.
3. **Rotate Binance API keys before wiring real orders — non-negotiable.**
   User chose to keep the exposed keys during paper phase (2026-07-14);
   advised meanwhile: disable withdrawals + IP-restrict the key on Binance.
4. Go live with the $200. Expectation set with user: ~1–3%/month average,
   lumpy months, −50%+ historical drawdowns, possibly months in cash.
   The #1 risk is abandoning the system mid-drawdown — remind, don't tinker.
5. Grow capital externally ($500–1k/month goal needs ~$30–60k at 1–2%/month);
   the engine scales as-is.

## Conventions

- Never commit or push unless the user asks.
- `.env` holds Binance + Telegram creds. **`.env` is tracked in git history —
  keys should be rotated and the file untracked (git rm --cached).** Never
  print or commit secrets.
- Public Binance endpoints need no keys — paper mode runs without secrets.
- Any new strategy idea goes through the gauntlet before touching the bot:
  real data → train/test split → profitable OOS (PF > ~1.3) → paper → live.
