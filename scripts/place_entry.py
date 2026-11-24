"""Stop-limit BUY entry + automatic protective OCO once it fills. Binance Spot.

Run by the user, never by Claude. Dry run by default: checks balance, filters
and price sanity and prints exactly what would be sent. --confirm places the
BUY. With --protect (the default when confirming), the script then waits and,
the moment the buy FILLS, places the OCO sell (take-profit + stop-limit) for the
BTC actually received. Keep the laptop awake (it runs under caffeinate) until it
prints "protected". Ctrl-C while waiting leaves the buy order open with NO
protection: place the OCO yourself (scripts/place_oco.py) or cancel the buy.

    ./venv/bin/python scripts/place_entry.py                  # dry run
    ./venv/bin/python scripts/place_entry.py --confirm        # place buy, then auto-protect
    ./venv/bin/python scripts/place_entry.py --cancel         # cancel open BUY orders

Defaults = the 2026-11-22 plan: buy 0.0006 BTC if BTC breaks the post-crash
bounce high (trigger 61,100 / limit 61,250); then TP 63,900, stop 59,000/58,900.
≈ +$1.55 / −$1.40 net. NOT a tested edge: the 4h checklist failed its backtest.
"""
import argparse
import os
import subprocess
import sys
import time
from decimal import Decimal

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from main import (  # noqa: E402
    API_KEY,
    API_SECRET,
    _binance_public_get,
    _binance_signed_request,
    get_free_balance,
    get_symbol_filters,
    round_down_step,
)

SYMBOL = "BTCUSDT"
FEE = 0.00075


def api(method, path, params=None):
    try:
        return _binance_signed_request(method, path, params)
    except requests.HTTPError as e:
        sys.exit(f"Binance error: {e.response.text}")


def place_oco(qty, tp, stop, stop_limit):
    return api("POST", "/api/v3/orderList/oco", {
        "symbol": SYMBOL, "side": "SELL", "quantity": qty,
        "aboveType": "LIMIT_MAKER", "abovePrice": tp,
        "belowType": "STOP_LOSS_LIMIT", "belowStopPrice": stop,
        "belowPrice": stop_limit, "belowTimeInForce": "GTC",
    })


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qty", default="0.00060")
    ap.add_argument("--trigger", default="61100.00", help="buy stop trigger (above price)")
    ap.add_argument("--limit", default="61250.00", help="max buy price after trigger")
    ap.add_argument("--tp", default="63900.00")
    ap.add_argument("--stop", default="59000.00")
    ap.add_argument("--stop-limit", default="58900.00")
    ap.add_argument("--confirm", action="store_true", help="actually place the buy")
    ap.add_argument("--no-protect", action="store_true", help="don't wait/auto-place the OCO")
    ap.add_argument("--cancel", action="store_true", help="cancel open BUY orders")
    ap.add_argument("--buy-limit", metavar="PRICE",
                    help="instead of a stop-limit breakout buy: LIMIT buy BELOW the price, sent as one "
                         "OTOCO so Binance itself attaches the TP/stop OCO on fill (no laptop needed)")
    ap.add_argument("--resume", metavar="ORDER_ID", help="don't place a buy; wait on this existing "
                    "buy order and auto-place the OCO when it fills")
    a = ap.parse_args()
    if not API_KEY or not API_SECRET:
        sys.exit("BINANCE_API_KEY / BINANCE_API_SECRET missing from .env")

    if a.resume:
        return protect(int(a.resume), a)
    if a.buy_limit:
        return limit_otoco(a)

    if a.cancel:
        buys = [o for o in api("GET", "/api/v3/openOrders", {"symbol": SYMBOL}) if o["side"] == "BUY"]
        if not buys:
            print("No open BUY orders.")
        for o in buys:
            print("Cancelled:", api("DELETE", "/api/v3/order", {"symbol": SYMBOL, "orderId": o["orderId"]})["status"])
        return

    price = float(_binance_public_get("/api/v3/ticker/price", {"symbol": SYMBOL})["price"])
    usdt = get_free_balance("USDT")
    q, trig, lim = float(a.qty), float(a.trigger), float(a.limit)
    tp, stop, sl = float(a.tp), float(a.stop), float(a.stop_limit)
    filt = get_symbol_filters(SYMBOL)
    cost_max = q * lim * (1 + FEE)
    win = q * tp * (1 - FEE) - q * trig * (1 + FEE)
    loss = q * sl * (1 - FEE) - q * lim * (1 + FEE)

    print(f"BTC now {price:,.2f} | free USDT {usdt:.2f}")
    print(f"BUY  {a.qty} BTC STOP_LOSS_LIMIT: trigger {a.trigger}, limit {a.limit} (GTC), max cost ≈ {cost_max:.2f} USDT")
    print(f"THEN OCO SELL: TP {a.tp} | stop {a.stop} / limit {a.stop_limit}")
    print(f"≈ net if TP: {win:+.2f} USD | if stop (worst): {loss:+.2f} USD")

    problems = []
    if not trig > price:
        problems.append("trigger must be ABOVE the current price (else it would buy now)")
    if not lim >= trig:
        problems.append("limit must be at or above the trigger")
    if not tp > lim:
        problems.append("take-profit must be above the buy limit")
    if not sl <= stop < trig:
        problems.append("need stop-limit <= stop < trigger")
    if cost_max > usdt:
        problems.append(f"max cost {cost_max:.2f} > free USDT {usdt:.2f}")
    if Decimal(a.qty) != round_down_step(a.qty, filt["step_size"]):
        problems.append(f"qty must be a multiple of {filt['step_size']}")
    if Decimal(str(q * trig)) < filt["min_notional"]:
        problems.append(f"order below min notional {filt['min_notional']}")
    if problems:
        sys.exit("Refusing:\n  - " + "\n  - ".join(problems))

    if not a.confirm:
        print("\nDry run only — nothing sent. Re-run with --confirm to place it.")
        return

    o = api("POST", "/api/v3/order", {
        "symbol": SYMBOL, "side": "BUY", "type": "STOP_LOSS_LIMIT", "timeInForce": "GTC",
        "quantity": a.qty, "price": a.limit, "stopPrice": a.trigger,
        "newOrderRespType": "RESULT",
    })
    oid = o["orderId"]
    print(f"\nBUY placed. orderId={oid} status={o.get('status', 'NEW')}")
    if a.no_protect:
        print(f"No auto-protect. Later: --resume {oid}, or place the OCO yourself once it fills.")
        return
    protect(oid, a)


def limit_otoco(a):
    price = float(_binance_public_get("/api/v3/ticker/price", {"symbol": SYMBOL})["price"])
    usdt = get_free_balance("USDT")
    filt = get_symbol_filters(SYMBOL)
    q, bl = float(a.qty), float(a.buy_limit)
    tp, stop, sl = float(a.tp), float(a.stop), float(a.stop_limit)
    cost = q * bl * (1 + FEE)
    print(f"BTC now {price:,.2f} | free USDT {usdt:.2f}")
    print(f"OTOCO: LIMIT BUY {a.qty} BTC @ {a.buy_limit} (GTC), cost ≈ {cost:.2f} USDT")
    print(f"  on fill → OCO SELL: TP {a.tp} | stop {a.stop} / limit {a.stop_limit}")
    print(f"≈ net if TP: {q * tp * (1 - FEE) - cost:+.2f} USD | if stop (worst): {q * sl * (1 - FEE) - cost:+.2f} USD")
    problems = []
    if not bl < price:
        problems.append("buy limit must be BELOW the current price (else it fills now as taker)")
    if not tp > bl:
        problems.append("take-profit must be above the buy limit")
    if not sl <= stop < bl:
        problems.append("need stop-limit <= stop < buy limit")
    if cost > usdt:
        problems.append(f"cost {cost:.2f} > free USDT {usdt:.2f}")
    if Decimal(a.qty) != round_down_step(a.qty, filt["step_size"]):
        problems.append(f"qty must be a multiple of {filt['step_size']}")
    if problems:
        sys.exit("Refusing:\n  - " + "\n  - ".join(problems))
    if not a.confirm:
        print("\nDry run only — nothing sent. Re-run with --confirm to place it.")
        return
    r = api("POST", "/api/v3/orderList/otoco", {
        "symbol": SYMBOL,
        "workingType": "LIMIT", "workingSide": "BUY", "workingPrice": a.buy_limit,
        "workingQuantity": a.qty, "workingTimeInForce": "GTC",
        "pendingSide": "SELL", "pendingQuantity": a.qty,
        "pendingAboveType": "LIMIT_MAKER", "pendingAbovePrice": a.tp,
        "pendingBelowType": "STOP_LOSS_LIMIT", "pendingBelowStopPrice": a.stop,
        "pendingBelowPrice": a.stop_limit, "pendingBelowTimeInForce": "GTC",
    })
    print(f"\nPlaced OTOCO. orderListId={r.get('orderListId')} status={r.get('listOrderStatus')}")
    for o in r.get("orderReports", []):
        print(f"  {o['side']} {o['type']} {o['origQty']} @ {o['price']} → {o['status']}")
    print("Binance attaches the TP/stop itself when the buy fills. "
          "To cancel the whole thing: ./venv/bin/python scripts/place_oco.py --cancel")


def protect(oid, a):
    filt = get_symbol_filters(SYMBOL)
    print(f"Waiting for fill of order {oid} to auto-place the OCO (checks every 15s; keep this running)...")
    if os.uname().sysname == "Darwin":
        subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
    while True:
        try:
            s = _binance_signed_request("GET", "/api/v3/order", {"symbol": SYMBOL, "orderId": oid})
        except Exception as e:
            print(f"  status check failed ({e}); retrying", flush=True)
            time.sleep(15)
            continue
        if s["status"] == "FILLED":
            break
        if s["status"] in ("CANCELED", "EXPIRED", "REJECTED"):
            sys.exit(f"Buy order {s['status']} — nothing to protect.")
        time.sleep(15)

    filled = float(s["executedQty"])
    avg = float(s["cummulativeQuoteQty"]) / filled
    free_btc = get_free_balance("BTC")
    qty = round_down_step(min(filled, free_btc), filt["step_size"])
    print(f"FILLED {filled} BTC @ avg {avg:,.2f}. Placing OCO for {qty} BTC...")
    r = place_oco(str(qty), a.tp, a.stop, a.stop_limit)
    print(f"protected ✅ orderListId={r.get('orderListId')} status={r.get('listOrderStatus')}")


if __name__ == "__main__":
    main()
