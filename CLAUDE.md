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

## Deployment status — PAUSED 2026-07-29 (VPS being destroyed)

Was deployed on a DigitalOcean droplet (`ubuntu-s-1vcpu-2gb-sgp1`, $12/mo,
Ubuntu 24.04, repo at `/root/ai-trader`) as systemd service `ai-trader`
(enabled = survives reboots, Restart=always) from 2026-07-14 to 2026-07-29.
**Paper burn-in PASSED** (15 days, one graceful restart survived correctly
via systemd, zero errors, zero state corruption — see gate 1 below). No live
trade was ever placed; real Binance balance stayed at $0.04 (never funded).

**User is destroying the droplet to stop the $12/mo cost while paused**
(reasoning: no live position, no funds deposited, BTC nowhere near the entry
trigger — lowest-risk possible moment to pause). Destroying (not just
powering off) is required to actually stop DO billing. `.env` is gitignored
and only existed on the droplet — user was told to save its contents (Telegram
token/chat ID + rotated Binance key/secret) externally before destroying;
everything else (all code) is already on GitHub main, current as of commit
`bd07b88`, nothing is lost by destroying the droplet.

**To resume — do this in order:**
1. Spin up a fresh droplet (any size — even $6/mo 1GB comfortably fits this
   bot; the old $12/mo 2GB was oversized for a ~47MB-RAM workload).
2. Follow [DEPLOY.md](DEPLOY.md) top to bottom (same as original deploy).
3. Restore `.env` (from the user's saved backup, or re-enter values).
4. **Update the Binance API key's IP restriction to the NEW droplet's IP** —
   the old IP is gone with the old droplet; skipping this makes `--check-live`
   and any live order fail auth (fails safe, but blocks operation until fixed).
5. Re-verify: `--check-live`, then a fresh burn-in stretch before trusting it
   again (the 15-day record was validated on infra that no longer exists).
6. Decide when to actually deposit funds and flip `LIVE_TRADING=true` —
   nothing about strategy validity expired during the pause, only the
   infra-uptime evidence needs re-establishing.

DO resize was attempted first (cheaper tier on the SAME droplet, no migration
needed) but DO does not allow shrinking disk on resize — the $4/$6 tiers were
greyed out ("not available because it has a smaller disk") since the existing
50GB disk is locked to the $12+/mo tiers. A same-provider fresh-droplet
migration to a smaller disk was considered and explicitly deferred in favor
of a full pause instead.

## Agreed gates to live trading (in order)

1. ~~Clean burn-in uptime record~~ ✅ **PASSED 2026-07-29.** 15 days, one
   graceful restart (systemd `enable` + `Restart=always` recovered it
   correctly, not a crash loop — confirmed via journalctl start/stop pairs),
   zero errors, zero state corruption, hourly heartbeats unbroken.
2. ~~Implement live order path~~ ✅ **DONE 2026-07-29.** main.py: hand-rolled
   HMAC-signed Binance REST client (no new deps — stdlib hmac/hashlib/decimal
   + existing requests). `LIVE_TRADING=true` in `.env` flips it (default
   stays PAPER). Sizes every order from the **actual live USDT/BTC balance**
   at that moment (get_free_balance), not remembered state — DCA deposits
   auto-deploy at the next BUY as required. MIN_NOTIONAL/LOT_SIZE filters
   fetched from Binance and respected (round_down_step). Safety cap
   `BINANCE_MAX_NOTIONAL_USD` (default $5000) refuses oversized orders and
   alerts instead. `--check-live` does a read-only balance/connectivity test
   with no order placed. Failed live orders leave `last_processed_close`
   unsaved so the next hourly check retries automatically. Full walkthrough:
   [DEPLOY.md](DEPLOY.md) "Going live" section.
   **Follow-up fix (commit bd07b88, same day):** order-response fields
   (`executedQty`/`cummulativeQuoteQty`) are the GROSS trade amount, not
   fee-net — fixed to read the real balance delta before/after each order
   instead, which is correct regardless of which asset pays the fee (BTC/USDT
   vs BNB discount). Trade *sizing* was never affected (always balance-based),
   only logged/state precision was.
3. ~~Rotate Binance API keys~~ ✅ **DONE 2026-07-29**, confirmed by user:
   Withdrawals disabled + IP-restricted (to the droplet that has since been
   destroyed — **the new droplet's IP must be added to this key's restriction
   when resuming**, see Deployment status above).
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
