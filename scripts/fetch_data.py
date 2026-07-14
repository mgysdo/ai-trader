"""Fetch BTCUSDT klines from Binance public REST (no API keys needed).

Paginates the public /api/v3/klines endpoint and writes clean OHLCV CSVs to
data/. Used to build a backtest dataset that matches the live bot's timeframes
(5m entries + 1h trend filter).

Usage:
    ./venv/bin/python scripts/fetch_data.py --interval 5m --months 12
    ./venv/bin/python scripts/fetch_data.py --interval 1h --months 12
"""

import argparse
import os
import time
from datetime import UTC, datetime, timedelta

import pandas as pd
import requests

BASE_URL = "https://api.binance.com/api/v3/klines"
SYMBOL = "BTCUSDT"
LIMIT = 1000  # Binance max per request.

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def fetch_klines(symbol, interval, start_ms, end_ms):
    """Yield raw kline rows from start_ms to end_ms, paginating forward."""
    cursor = start_ms
    while cursor < end_ms:
        resp = requests.get(
            BASE_URL,
            params={
                "symbol": symbol,
                "interval": interval,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": LIMIT,
            },
            timeout=20,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break

        for row in batch:
            yield row

        # Advance cursor past the last open_time we received.
        last_open = batch[-1][0]
        cursor = last_open + 1

        # Stop if Binance returned a short (final) page.
        if len(batch) < LIMIT:
            break

        time.sleep(0.25)  # Be polite to the public endpoint.


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", default="5m", help="e.g. 5m, 1h")
    parser.add_argument("--months", type=int, default=12)
    parser.add_argument("--symbol", default=SYMBOL)
    args = parser.parse_args()

    end = datetime.now(UTC)
    start = end - timedelta(days=args.months * 31)
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)

    print(
        f"Fetching {args.symbol} {args.interval} "
        f"from {start.date()} to {end.date()} ..."
    )

    rows = list(fetch_klines(args.symbol, args.interval, start_ms, end_ms))
    if not rows:
        print("No data returned.")
        return

    cols = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "number_of_trades",
        "taker_buy_base", "taker_buy_quote", "ignore",
    ]
    df = pd.DataFrame(rows, columns=cols)

    df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = df[c].astype(float)

    df = df[["timestamp", "open", "high", "low", "close", "volume", "close_time"]]
    df = df.drop_duplicates(subset="timestamp").sort_values("timestamp")

    os.makedirs(DATA_DIR, exist_ok=True)
    out = os.path.join(DATA_DIR, f"{args.symbol}_{args.interval}.csv")
    df.to_csv(out, index=False)

    print(
        f"Saved {len(df):,} rows -> {os.path.relpath(out)}  "
        f"({df['timestamp'].min()} .. {df['timestamp'].max()})"
    )


if __name__ == "__main__":
    main()
