import warnings
from datetime import time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf
from backtesting import Backtest, Strategy


warnings.filterwarnings(
    "ignore",
    message="If you want to use multi-process optimization",
    category=RuntimeWarning,
)


TICKER = "EURUSD=X"
INTERVAL = "15m"
PERIOD = "60d"
LOWER_INTERVAL = "5m"
BACKTEST_COMMISSION = 0.00002
BACKTEST_SPREAD = 0.00006
PIP_SIZE = 0.0001
NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def ema(series, period):
    return pd.Series(series).ewm(span=period, adjust=False).mean()


def rsi(series, period=14):
    series = pd.Series(series)
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def atr(high, low, close, period=14):
    high = pd.Series(high)
    low = pd.Series(low)
    close = pd.Series(close)
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def normalize_ohlc(df):
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]
    df = df.rename(columns={c: c.lower() for c in df.columns})
    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[keep]
    if df.index.tz is None:
        df.index = df.index.tz_localize(UTC)
    else:
        df.index = df.index.tz_convert(UTC)
    return df.sort_index()


def download_data(interval, period):
    raw = yf.download(
        TICKER,
        interval=interval,
        period=period,
        auto_adjust=False,
        progress=False,
        prepost=False,
        threads=False,
    )
    if raw.empty:
        raise RuntimeError(f"No data returned for {TICKER} {interval} {period}")
    return normalize_ohlc(raw)


def session_name(local_time):
    if time(20, 0) <= local_time or local_time < time(0, 0):
        return "asian"
    if time(3, 0) <= local_time < time(8, 0):
        return "london"
    if time(8, 0) <= local_time < time(12, 0):
        return "new_york"
    return "off"


def build_liquidity_levels(df):
    frame = df.copy()
    local_index = frame.index.tz_convert(NY)
    frame["local_date"] = local_index.date
    frame["local_time"] = local_index.time
    frame["session"] = frame["local_time"].apply(session_name)

    day_stats = (
        frame.groupby("local_date")[["high", "low"]]
        .agg(day_high=("high", "max"), day_low=("low", "min"))
        .shift(1)
    )

    last_closed_session_high = np.nan
    last_closed_session_low = np.nan
    last_session_id = None
    current_session_high = np.nan
    current_session_low = np.nan
    current_session_key = None
    session_records = []

    for ts, row in frame.iterrows():
        key = (row["local_date"], row["session"])
        session = row["session"]

        if session == "off":
            if current_session_key is not None:
                last_closed_session_high = current_session_high
                last_closed_session_low = current_session_low
                current_session_key = None
                current_session_high = np.nan
                current_session_low = np.nan

            session_records.append(
                {
                    "day_high": day_stats.loc[row["local_date"], "day_high"] if row["local_date"] in day_stats.index else np.nan,
                    "day_low": day_stats.loc[row["local_date"], "day_low"] if row["local_date"] in day_stats.index else np.nan,
                    "session_high": last_closed_session_high,
                    "session_low": last_closed_session_low,
                }
            )
            continue

        if key != current_session_key:
            if current_session_key is not None:
                last_closed_session_high = current_session_high
                last_closed_session_low = current_session_low
            current_session_key = key
            current_session_high = row["high"]
            current_session_low = row["low"]
        else:
            current_session_high = max(current_session_high, row["high"])
            current_session_low = min(current_session_low, row["low"])

        last_session_id = session
        session_records.append(
            {
                "day_high": day_stats.loc[row["local_date"], "day_high"] if row["local_date"] in day_stats.index else np.nan,
                "day_low": day_stats.loc[row["local_date"], "day_low"] if row["local_date"] in day_stats.index else np.nan,
                "session_high": last_closed_session_high,
                "session_low": last_closed_session_low,
            }
        )

    levels = pd.DataFrame(session_records, index=frame.index)
    levels.index = frame.index
    return pd.concat([frame, levels], axis=1)


def find_pivots(df, strength=2):
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    pivot_high = np.full(len(df), np.nan)
    pivot_low = np.full(len(df), np.nan)

    for i in range(strength, len(df) - strength):
        hi_window = highs[i - strength:i + strength + 1]
        lo_window = lows[i - strength:i + strength + 1]
        if highs[i] == hi_window.max() and hi_window.argmax() == strength:
            pivot_high[i] = highs[i]
        if lows[i] == lo_window.min() and lo_window.argmin() == strength:
            pivot_low[i] = lows[i]

    df = df.copy()
    df["pivot_high"] = pivot_high
    df["pivot_low"] = pivot_low
    return df


def build_structure(df):
    df = df.copy()
    df["ema20"] = ema(df["close"], 20)
    df["ema50"] = ema(df["close"], 50)
    df["ema20_slope"] = df["ema20"].diff()
    df["rsi14"] = rsi(df["close"], 14)
    df["atr14"] = atr(df["high"], df["low"], df["close"], 14)
    df = find_pivots(df, strength=2)

    leg_direction = np.nan
    leg_low = np.nan
    leg_high = np.nan
    fib_618 = np.nan
    fib_786 = np.nan

    records = []
    last_pivot_low = np.nan
    last_pivot_high = np.nan

    for _, row in df.iterrows():
        if not np.isnan(row["pivot_low"]):
            last_pivot_low = row["pivot_low"]
            if not np.isnan(last_pivot_high) and last_pivot_high > last_pivot_low:
                leg_direction = 1
                leg_low = last_pivot_low
                leg_high = last_pivot_high
                fib_618 = leg_high - (leg_high - leg_low) * 0.618
                fib_786 = leg_high - (leg_high - leg_low) * 0.786

        if not np.isnan(row["pivot_high"]):
            last_pivot_high = row["pivot_high"]
            if not np.isnan(last_pivot_low) and last_pivot_high > last_pivot_low:
                leg_direction = -1
                leg_low = last_pivot_low
                leg_high = last_pivot_high
                fib_618 = leg_low + (leg_high - leg_low) * 0.618
                fib_786 = leg_low + (leg_high - leg_low) * 0.786

        records.append(
            {
                "leg_direction": leg_direction,
                "leg_low": leg_low,
                "leg_high": leg_high,
                "fib_618": fib_618,
                "fib_786": fib_786,
                "trend_bullish": int(row["ema20"] > row["ema50"] and row["ema20_slope"] > 0),
                "trend_bearish": int(row["ema20"] < row["ema50"] and row["ema20_slope"] < 0),
            }
        )

    structure = pd.DataFrame(records, index=df.index)
    return pd.concat([df, structure], axis=1)


def build_daily_bias(df_15m):
    daily = df_15m[["close"]].resample("1D").last().dropna().copy()
    daily["daily_ema_fast"] = ema(daily["close"], 3)
    daily["daily_ema_slow"] = ema(daily["close"], 8)
    daily["daily_ema_slope"] = daily["daily_ema_fast"].diff()
    daily["daily_bullish"] = (
        (daily["daily_ema_fast"] > daily["daily_ema_slow"])
        & (daily["daily_ema_slope"] > 0)
    ).astype(int)
    daily["daily_bearish"] = (
        (daily["daily_ema_fast"] < daily["daily_ema_slow"])
        & (daily["daily_ema_slope"] < 0)
    ).astype(int)
    # Shift by one daily bar to avoid lookahead bias.
    daily = daily.shift(1)
    return daily[["daily_bullish", "daily_bearish"]]


def build_lower_timeframe_confirmation(df_5m):
    df = df_5m.copy()
    df["ema9_5m"] = ema(df["close"], 9)
    df["ema21_5m"] = ema(df["close"], 21)
    df["rsi14_5m"] = rsi(df["close"], 14)
    df["bullish_impulse_5m"] = (
        (df["ema9_5m"] > df["ema21_5m"])
        & (df["close"] > df["ema21_5m"])
        & (df["close"] > df["open"])
        & (df["rsi14_5m"] >= 45)
    ).astype(int)
    df["bearish_impulse_5m"] = (
        (df["ema9_5m"] < df["ema21_5m"])
        & (df["close"] < df["ema21_5m"])
        & (df["close"] < df["open"])
        & (df["rsi14_5m"] <= 55)
    ).astype(int)

    lower_15m = (
        df.resample("15min", label="right", closed="right")
        .agg(
            {
                "ema9_5m": "last",
                "ema21_5m": "last",
                "rsi14_5m": "last",
                "bullish_impulse_5m": "max",
                "bearish_impulse_5m": "max",
            }
        )
        .dropna(subset=["ema9_5m", "ema21_5m", "rsi14_5m"])
    )
    return lower_15m[["ema9_5m", "ema21_5m", "rsi14_5m", "bullish_impulse_5m", "bearish_impulse_5m"]]


def prepare_data():
    df_15m = download_data(INTERVAL, PERIOD)
    df_5m = download_data(LOWER_INTERVAL, PERIOD)

    lower_confirmation = build_lower_timeframe_confirmation(df_5m)
    df_15m = build_liquidity_levels(df_15m)
    df_15m = build_structure(df_15m)
    daily_bias = build_daily_bias(df_15m)
    df_15m = pd.merge_asof(
        df_15m.sort_index(),
        lower_confirmation.sort_index(),
        left_index=True,
        right_index=True,
        direction="backward",
    )
    df_15m = pd.merge_asof(
        df_15m.sort_index(),
        daily_bias.sort_index(),
        left_index=True,
        right_index=True,
        direction="backward",
    )
    df = df_15m.dropna(subset=[
        "open",
        "high",
        "low",
        "close",
        "ema20",
        "ema50",
        "rsi14",
        "atr14",
        "ema9_5m",
        "ema21_5m",
        "rsi14_5m",
        "daily_bullish",
        "daily_bearish",
    ])
    df = df.rename(columns={
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
    })
    return df


class SimonEURUSDStrategy(Strategy):
    risk_per_trade = 0.0025
    rr_ratio = 1.2
    atr_buffer = 0.35
    bull_rsi_min = 42
    bear_rsi_max = 62
    pending_ttl_bars = 4
    max_hold_bars = 12
    min_5m_score = 2
    cooldown_bars = 16
    min_risk_spread_mult = 2.0
    require_daily_bias = False

    def finalize(self):
        # Force-close any open position at the end of the backtest
        if self.position:
            self.position.close()

    def init(self):
        self.pending_direction = None
        self.pending_stop = np.nan
        self.pending_take_profit = np.nan
        self.pending_ttl = 0
        self.trade_bars = 0  # Track bars since entry
        self.last_entry_bar = -10_000
        self.c_total = 0
        self.c_trend = 0
        self.c_sweep = 0
        self.c_fib_valid = 0
        self.c_fib_zone = 0
        self.c_rsi = 0
        self.c_setup = 0
        self.c_entry = 0

    def next(self):
        bar_idx = len(self.data) - 1
        min_risk_distance = max(BACKTEST_SPREAD * self.min_risk_spread_mult, 1e-5)
        price = self.data.Close[-1]
        open_ = self.data.Open[-1]
        high = self.data.High[-1]
        low = self.data.Low[-1]
        atr_value = self.data.atr14[-1]
        rsi_value = self.data.rsi14[-1]
        trend_bullish = bool(self.data.trend_bullish[-1])
        trend_bearish = bool(self.data.trend_bearish[-1])
        daily_bullish = bool(self.data.daily_bullish[-1])
        daily_bearish = bool(self.data.daily_bearish[-1])
        fib_618 = self.data.fib_618[-1]
        fib_786 = self.data.fib_786[-1]
        leg_low = self.data.leg_low[-1]
        leg_high = self.data.leg_high[-1]
        day_low = self.data.day_low[-1]
        day_high = self.data.day_high[-1]
        ema9_5m = self.data.ema9_5m[-1]
        ema21_5m = self.data.ema21_5m[-1]
        rsi14_5m = self.data.rsi14_5m[-1]
        bullish_impulse_5m = bool(self.data.bullish_impulse_5m[-1])
        bearish_impulse_5m = bool(self.data.bearish_impulse_5m[-1])
        bullish_5m_score = int(bullish_impulse_5m) + int(ema9_5m > ema21_5m) + int(rsi14_5m >= 45)
        bearish_5m_score = int(bearish_impulse_5m) + int(ema9_5m < ema21_5m) + int(rsi14_5m <= 55)

        if np.isnan(atr_value) or np.isnan(rsi_value):
            return

        self.c_total += 1

        if np.isnan(leg_low) or np.isnan(leg_high) or leg_high <= leg_low:
            return

        if np.isnan(ema9_5m) or np.isnan(ema21_5m) or np.isnan(rsi14_5m):
            return

        if self.require_daily_bias:
            trend_bullish = trend_bullish and daily_bullish
            trend_bearish = trend_bearish and daily_bearish

        sweep_below_day = not np.isnan(day_low) and low < day_low
        sweep_above_day = not np.isnan(day_high) and high > day_high

        trend_active = trend_bullish or trend_bearish
        if trend_active:
            self.c_trend += 1

        sweep_active = sweep_below_day or sweep_above_day
        if trend_active and sweep_active:
            self.c_sweep += 1

        fib_valid = not np.isnan(fib_618) and not np.isnan(fib_786)
        if trend_active and sweep_active and fib_valid:
            self.c_fib_valid += 1

        fib_zone_bull = fib_valid and low <= fib_618 and high >= fib_786
        fib_zone_bear = fib_valid and low <= fib_786 and high >= fib_618
        fib_zone = fib_zone_bull or fib_zone_bear
        if trend_active and sweep_active and fib_zone:
            self.c_fib_zone += 1

        rsi_ok_bull = rsi_value >= self.bull_rsi_min and price > fib_618 if fib_valid else False
        rsi_ok_bear = rsi_value <= self.bear_rsi_max and price < fib_618 if fib_valid else False
        if trend_active and sweep_active and fib_zone and (rsi_ok_bull or rsi_ok_bear):
            self.c_rsi += 1

        bullish_5m_confirmation = bullish_5m_score >= self.min_5m_score
        bearish_5m_confirmation = bearish_5m_score >= self.min_5m_score
        cooldown_active = (bar_idx - self.last_entry_bar) < self.cooldown_bars

        # Manage currently open trade before considering any new setup.
        if self.position:
            self.trade_bars += 1
            if self.trade_bars >= self.max_hold_bars:
                self.position.close()
                self.trade_bars = 0
            return

        bullish_retrace = (
            trend_bullish
            and not np.isnan(fib_618)
            and not np.isnan(fib_786)
            and low <= fib_618
            and high >= fib_786
            and price > fib_618
            and rsi_value >= self.bull_rsi_min
        )

        bearish_retrace = (
            trend_bearish
            and not np.isnan(fib_618)
            and not np.isnan(fib_786)
            and low <= fib_786
            and high >= fib_618
            and price < fib_618
            and rsi_value <= self.bear_rsi_max
        )

        if self.pending_ttl > 0:
            self.pending_ttl -= 1
            if self.pending_ttl == 0:
                self.pending_direction = None
                self.pending_stop = np.nan
                self.pending_take_profit = np.nan

        if self.pending_direction == "LONG" and bullish_5m_confirmation and not cooldown_active:
            risk = price - self.pending_stop
            if risk <= min_risk_distance:
                self.pending_direction = None
                return
            tp = price + risk * self.rr_ratio
            if not (self.pending_stop < price < tp):
                self.pending_direction = None
                return
            size = max(1, int((self.equity * self.risk_per_trade) / risk))
            self.buy(size=size, sl=self.pending_stop, tp=tp)
            self.c_entry += 1
            self.last_entry_bar = bar_idx
            self.pending_direction = None
            self.pending_stop = np.nan
            self.pending_take_profit = np.nan
            self.pending_ttl = 0
            self.trade_bars = 0  # Start bar count for time exit

        if self.pending_direction is None:
            if bullish_retrace or bearish_retrace:
                self.c_setup += 1

            if bullish_retrace:
                self.pending_direction = "LONG"
                self.pending_stop = min(
                    low,
                    day_low if not np.isnan(day_low) else low,
                    leg_low,
                ) - atr_value * self.atr_buffer
                risk = price - self.pending_stop
                if risk > min_risk_distance:
                    self.pending_take_profit = price + risk * self.rr_ratio
                    self.pending_ttl = self.pending_ttl_bars
                else:
                    self.pending_direction = None

            elif bearish_retrace:
                self.pending_direction = "SHORT"
                self.pending_stop = max(
                    high,
                    day_high if not np.isnan(day_high) else high,
                    leg_high,
                ) + atr_value * self.atr_buffer
                risk = self.pending_stop - price
                if risk > min_risk_distance:
                    self.pending_take_profit = price - risk * self.rr_ratio
                    self.pending_ttl = self.pending_ttl_bars
                else:
                    self.pending_direction = None
            return

        if self.pending_direction == "SHORT" and bearish_5m_confirmation and not cooldown_active:
            risk = self.pending_stop - price
            if risk <= min_risk_distance:
                self.pending_direction = None
                return
            tp = price - risk * self.rr_ratio
            if not (tp < price < self.pending_stop):
                self.pending_direction = None
                return
            size = max(1, int((self.equity * self.risk_per_trade) / risk))
            self.sell(size=size, sl=self.pending_stop, tp=tp)
            self.c_entry += 1
            self.last_entry_bar = bar_idx
            self.pending_direction = None
            self.pending_stop = np.nan
            self.pending_take_profit = np.nan
            self.pending_ttl = 0
            self.trade_bars = 0  # Start bar count for time exit

def print_metrics(stats, strategy_instance=None):
    trades = stats["_trades"]
    total_pips = np.nan
    avg_pips = np.nan
    if len(trades):
        signed_direction = np.sign(trades["Size"].astype(float))
        pip_series = ((trades["ExitPrice"] - trades["EntryPrice"]) * signed_direction) / PIP_SIZE
        total_pips = float(pip_series.sum())
        avg_pips = float(pip_series.mean())

    print("\n===== EUR/USD SIMON STRATEGY =====")
    print(f"Return [%]: {stats['Return [%]']:.5f}")
    print(f"Buy & Hold Return [%]: {stats['Buy & Hold Return [%]']:.5f}")
    print(f"Max. Drawdown [%]: {stats['Max. Drawdown [%]']:.5f}")
    print(f"# Trades: {int(stats['# Trades'])}")
    print(f"Win Rate [%]: {stats['Win Rate [%]']:.2f}")
    print(f"Profit Factor: {stats['Profit Factor']:.5f}")
    if np.isnan(total_pips):
        print("Total Pips: n/a")
        print("Avg Pips/Trade: n/a")
    else:
        print(f"Total Pips: {total_pips:.2f}")
        print(f"Avg Pips/Trade: {avg_pips:.2f}")
    if strategy_instance is not None:
        s = strategy_instance
        print("\n===== CONDITION FUNNEL =====")
        print(f"Bars evaluated (valid indicators):  {s.c_total}")
        print(f"  + trend active:                   {s.c_trend}")
        print(f"  + day sweep:                      {s.c_sweep}")
        print(f"  + fib levels valid:               {s.c_fib_valid}")
        print(f"  + bar spans fib zone:             {s.c_fib_zone}")
        print(f"  + RSI + close filter:             {s.c_rsi}")
        print(f"  = setup bars:                     {s.c_setup}")
        print(f"  = entries executed:               {s.c_entry}")


def main():
    data = prepare_data()
    print(f"Loaded {len(data)} EUR/USD 15m bars")
    bt = Backtest(
        data,
        SimonEURUSDStrategy,
        cash=100000,
        commission=BACKTEST_COMMISSION,
        spread=BACKTEST_SPREAD,
        exclusive_orders=False,
        finalize_trades=True,
    )
    stats = bt.run()
    print_metrics(stats, stats._strategy)


if __name__ == "__main__":
    main()