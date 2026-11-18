"""Place a protective OCO sell (take-profit + stop-limit) on Binance Spot.

Run by the user, never by Claude. Dry-run by default: prints exactly what
would be sent and checks your free balance. Add --confirm to actually place.

    ./venv/bin/python scripts/place_oco.py                 # dry run
    ./venv/bin/python scripts/place_oco.py --confirm       # place it

Defaults = the plan for the 0.0006 BTC bought at 64,384.93 on 2026-11-17:
  take-profit LIMIT_MAKER 65,400  (≈ +$0.55 net)
  stop trigger 61,378 / stop limit 61,255  (≈ −$1.93 net, −5% of capital)
Whichever fills first cancels the other. Cancel any time in the Binance app
(Orders → Open Orders) or with --cancel.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from main import (  # noqa: E402  (reuses the bot's HMAC-signed client + .env)
    API_KEY,
    API_SECRET,
    _binance_public_get,
    _binance_signed_request,
    get_free_balance,
)

SYMBOL = "BTCUSDT"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qty", default="0.0006")
    ap.add_argument("--tp", default="65400.00", help="take-profit limit price")
    ap.add_argument("--stop", default="61378.00", help="stop trigger price")
    ap.add_argument("--stop-limit", default="61255.00", help="stop limit price")
    ap.add_argument("--confirm", action="store_true", help="actually place it")
    ap.add_argument("--cancel", action="store_true", help="list + cancel open OCOs")
    a = ap.parse_args()

    if not API_KEY or not API_SECRET:
        sys.exit("BINANCE_API_KEY / BINANCE_API_SECRET missing from .env")

    if a.cancel:
        lists = _binance_signed_request("GET", "/api/v3/openOrderList")
        if not lists:
            print("No open OCO order lists.")
        for ol in lists:
            print(f"Cancelling orderListId {ol['orderListId']} ...")
            print(_binance_signed_request(
                "DELETE", "/api/v3/orderList",
                {"symbol": ol["symbol"], "orderListId": ol["orderListId"]}))
        return

    price = float(_binance_public_get("/api/v3/ticker/price", {"symbol": SYMBOL})["price"])
    free_btc = get_free_balance("BTC")
    qty, tp, stop, stop_lim = float(a.qty), float(a.tp), float(a.stop), float(a.stop_limit)

    print(f"BTC now {price:,.2f} | free BTC {free_btc:.8f}")
    print(f"SELL {a.qty} BTC as OCO:")
    print(f"  above: LIMIT_MAKER @ {a.tp}")
    print(f"  below: STOP_LOSS_LIMIT trigger {a.stop}, limit {a.stop_limit} (GTC)")

    problems = []
    if free_btc < qty:
        problems.append(f"free BTC {free_btc} < qty {qty} (an open order may be holding it)")
    if not tp > price:
        problems.append("take-profit must be ABOVE the current price")
    if not stop < price:
        problems.append("stop trigger must be BELOW the current price")
    if not stop_lim <= stop:
        problems.append("stop limit must be at or below the stop trigger")
    if problems:
        sys.exit("Refusing:\n  - " + "\n  - ".join(problems))

    if not a.confirm:
        print("\nDry run only — nothing sent. Re-run with --confirm to place it.")
        return

    resp = _binance_signed_request("POST", "/api/v3/orderList/oco", {
        "symbol": SYMBOL,
        "side": "SELL",
        "quantity": a.qty,
        "aboveType": "LIMIT_MAKER",
        "abovePrice": a.tp,
        "belowType": "STOP_LOSS_LIMIT",
        "belowStopPrice": a.stop,
        "belowPrice": a.stop_limit,
        "belowTimeInForce": "GTC",
    })
    print(f"\nPlaced. orderListId={resp.get('orderListId')} status={resp.get('listOrderStatus')}")
    for o in resp.get("orderReports", []):
        print(f"  {o['type']:16s} {o['side']} {o['origQty']} @ {o['price']}"
              f"{'  stop ' + o['stopPrice'] if float(o.get('stopPrice', 0)) else ''}  → {o['status']}")


if __name__ == "__main__":
    main()
