# Deploying to the DigitalOcean VPS

The bot is tiny (one HTTP request/hour) — the smallest droplet works.
Paper mode needs **no Binance API keys**; only Telegram creds in `.env`.

## 0. Before touching the VPS (on your machine)

1. **Rotate your Binance API keys** (the old ones are in git history).
2. Push the repo: `git push origin main`.

## 1. Stop and clear the old bot (on the VPS)

```bash
ssh root@YOUR_DROPLET_IP

# Stop whatever is still running (old 5m bot / eurusd bot):
cd ~/ai-trader && ./scripts/botctl.sh stop || true
pkill -f "python.*main.py" || true
pkill -f "eurusd_paper_bot" || true
pgrep -af python   # verify: nothing trading-related left
```

## 2. Update the code

```bash
cd ~/ai-trader
git fetch origin
git reset --hard origin/main     # old local edits are superseded
```

(Fresh droplet instead: `git clone https://github.com/mgysdo/ai-trader.git ~/ai-trader`)

## 3. Python environment

```bash
apt update && apt install -y python3-venv
cd ~/ai-trader
rm -rf venv
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

## 4. Configure

```bash
cat > .env <<'ENV'
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id
ENV
chmod 600 .env
```

No Binance keys needed for paper mode.

## 5. Smoke test

```bash
./venv/bin/python main.py --once
```

Expected: one log line with `close=... sma100=... pos=USDT equity=$200.00`,
plus `allocator_state.json` created. Fresh state starts at $200 USDT.

## 6. Install as a service (survives reboots)

```bash
cp deploy/ai-trader.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now ai-trader
```

If your clone is not at `/root/ai-trader`, edit the two paths in the unit first.

## 7. Verify

```bash
systemctl status ai-trader        # active (running)
journalctl -fu ai-trader          # hourly check lines
cat allocator_state.json          # position/balances
```

You'll get a Telegram message on every BUY/SELL switch (expect ~5/year —
silence is normal and correct).

## Updating later

```bash
cd ~/ai-trader && git pull && systemctl restart ai-trader
```

`allocator_state.json` is gitignored, so restarts/updates never lose position
state. To reset the paper account, stop the service, delete
`allocator_state.json` + `allocator_trades.csv`, start again.

## Going live (only after burn-in has passed)

The order path sizes every trade from your **actual** Binance USDT/BTC
balance at the moment of the switch — never from a remembered number — so
monthly DCA deposits into the account auto-deploy at the next BUY signal
with no code or config change.

**Do this in order — do not skip step 1:**

1. **Rotate your Binance API keys.** Binance → API Management → delete the
   old key → create a new one. On the new key: enable **Spot Trading**,
   **disable Withdrawals**, and **IP-restrict** it to the droplet's IP.
2. Update `.env` on the droplet:
   ```bash
   cat >> .env <<'ENV'
   BINANCE_API_KEY=your_new_key
   BINANCE_API_SECRET=your_new_secret
   ENV
   ```
3. **Test read-only connectivity before enabling trading** — this does not
   place any order:
   ```bash
   ./venv/bin/python main.py --check-live
   ```
   Expect your real free USDT/BTC balances to print. If this errors, fix it
   before continuing (bad key, wrong permissions, IP restriction mismatch).
4. Flip the switch:
   ```bash
   echo 'LIVE_TRADING=true' >> .env
   systemctl restart ai-trader
   journalctl -fu ai-trader   # confirm: "mode=LIVE"
   ```
5. A safety cap (`BINANCE_MAX_NOTIONAL_USD`, default $5000) blocks any single
   order above that size and alerts instead of trading — raise it in `.env`
   only once the account has genuinely grown that large via DCA.

To go back to paper mode: remove `LIVE_TRADING=true` from `.env` (or set it
to `false`) and restart the service.
