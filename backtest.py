import pandas as pd
import numpy as np
import warnings

from backtesting import Backtest, Strategy

warnings.filterwarnings(
    "ignore",
    message="If you want to use multi-process optimization",
    category=RuntimeWarning,
)


# =========================
# LOAD CSV
# =========================

df = pd.read_csv("BTCUSDT_1h.csv")

print(df.columns)

df["timestamp"] = pd.to_datetime(df["timestamp"])

df = df.rename(columns={
    "open": "Open",
    "high": "High",
    "low": "Low",
    "close": "Close",
    "volume": "Volume"
})

df = df[
    [
        "timestamp",
        "Open",
        "High",
        "Low",
        "Close",
        "Volume"
    ]
]

df.set_index("timestamp", inplace=True)


# =========================
# INDICATORS
# =========================

def EMA(series, period):
    return pd.Series(series).ewm(
        span=period,
        adjust=False
    ).mean()


def RSI(series, period=14):
    series = pd.Series(series)

    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()

    rs = avg_gain / avg_loss

    rsi = 100 - (100 / (1 + rs))

    return rsi


def ATR(high, low, close, period=14):
    high = pd.Series(high)
    low = pd.Series(low)
    close = pd.Series(close)

    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.rolling(period).mean()

    return atr


# =========================
# STRATEGY
# =========================

class EMARSIMomentumStrategy(Strategy):

    fast_ema = 9
    slow_ema = 21

    rsi_period = 14

    # Beginner-safe default: risk only 0.25% equity per trade
    risk_per_trade = 0.0025

    atr_period = 14
    atr_percent_min = 0.5

    rr_ratio = 2
    long_rsi_low = 60
    long_rsi_high = 70

    def init(self):

        close = self.data.Close
        high = self.data.High
        low = self.data.Low

        self.fastEMA = self.I(
            EMA,
            close,
            self.fast_ema
        )

        self.slowEMA = self.I(
            EMA,
            close,
            self.slow_ema
        )

        self.rsi = self.I(
            RSI,
            close,
            self.rsi_period
        )

        self.atr = self.I(
            ATR,
            high,
            low,
            close,
            self.atr_period
        )

    def next(self):

        price = self.data.Close[-1]

        fastEMA = self.fastEMA[-1]
        slowEMA = self.slowEMA[-1]
        slowEMA_prev = self.slowEMA[-2]

        rsi = self.rsi[-1]
        atr = self.atr[-1]

        if np.isnan(atr) or np.isnan(slowEMA_prev):
            return

        # Skip low-volatility candles to avoid weak setups.
        atr_percent = (atr / price) * 100
        if atr_percent < self.atr_percent_min:
            return

        # =========================
        # LONG ENTRY
        # =========================

        if (
            not self.position
            and fastEMA > slowEMA
            and price > slowEMA
            and slowEMA > slowEMA_prev
            and self.long_rsi_low <= rsi <= self.long_rsi_high
        ):

            stop_loss = price - (1.5 * atr)

            risk_amount = self.equity * self.risk_per_trade

            risk_per_unit = abs(price - stop_loss)

            if risk_per_unit <= 0:
                return

            position_size = risk_amount / risk_per_unit

            # Prevent margin issue
            max_size = self.equity * 0.95 / price

            position_size = min(
                position_size,
                max_size
            )

            position_size = max(1, int(position_size))

            take_profit = price + (
                (price - stop_loss)
                * self.rr_ratio
            )

            self.buy(
                size=position_size,
                sl=stop_loss,
                tp=take_profit
            )

        # SHORT entry disabled for beginner long-only baseline.


# =========================
# BACKTEST (TRAIN / TEST)
# =========================

def run_backtest(dataset):
    bt = Backtest(
        dataset,
        EMARSIMomentumStrategy,
        cash=100000,
        commission=0.001,
        exclusive_orders=True,
        finalize_trades=True
    )
    return bt, bt.run()


def optimize_train(train_dataset):
    bt = Backtest(
        train_dataset,
        EMARSIMomentumStrategy,
        cash=100000,
        commission=0.001,
        exclusive_orders=True,
        finalize_trades=True
    )

    stats = bt.optimize(
        long_rsi_low=range(56, 64, 2),
        long_rsi_high=range(66, 76, 2),
        atr_percent_min=[0.4, 0.5, 0.6],
        rr_ratio=[1.5, 2.0, 2.5],
        maximize="Return [%]",
        constraint=lambda p: p.long_rsi_low < p.long_rsi_high,
        return_heatmap=False
    )

    best = {
        "long_rsi_low": stats["_strategy"].long_rsi_low,
        "long_rsi_high": stats["_strategy"].long_rsi_high,
        "atr_percent_min": stats["_strategy"].atr_percent_min,
        "rr_ratio": stats["_strategy"].rr_ratio,
    }

    return best, stats


def print_core_metrics(title, stats):
    print(f"\n===== {title} =====")
    print(f"Return [%]: {stats['Return [%]']:.5f}")
    print(f"Max. Drawdown [%]: {stats['Max. Drawdown [%]']:.5f}")
    print(f"# Trades: {int(stats['# Trades'])}")
    print(f"Profit Factor: {stats['Profit Factor']:.5f}")


def run_walk_forward(dataset, train_ratio=0.5, test_ratio=0.2, step_ratio=0.1):
    total_rows = len(dataset)

    train_size = int(total_rows * train_ratio)
    test_size = int(total_rows * test_ratio)
    step_size = int(total_rows * step_ratio)

    if train_size <= 0 or test_size <= 0 or step_size <= 0:
        return pd.DataFrame()

    window = 1
    start = 0
    results = []

    while start + train_size + test_size <= total_rows:
        train_slice = dataset.iloc[start:start + train_size].copy()
        test_start = start + train_size
        test_end = test_start + test_size
        test_slice = dataset.iloc[test_start:test_end].copy()

        best_params, _ = optimize_train(train_slice)

        test_bt = Backtest(
            test_slice,
            EMARSIMomentumStrategy,
            cash=100000,
            commission=0.001,
            exclusive_orders=True,
            finalize_trades=True
        )
        test_stats = test_bt.run(**best_params)

        results.append({
            "window": window,
            "train_start": train_slice.index[0],
            "train_end": train_slice.index[-1],
            "test_start": test_slice.index[0],
            "test_end": test_slice.index[-1],
            "test_return_pct": float(test_stats["Return [%]"]),
            "test_max_dd_pct": float(test_stats["Max. Drawdown [%]"]),
            "test_trades": int(test_stats["# Trades"]),
            "test_profit_factor": float(test_stats["Profit Factor"]),
        })

        window += 1
        start += step_size

    return pd.DataFrame(results)


def print_walk_forward_summary(wf_df):
    if wf_df.empty:
        print("\n===== WALK-FORWARD SUMMARY =====")
        print("Not enough data for walk-forward windows.")
        return

    print("\n===== WALK-FORWARD SUMMARY =====")
    display_cols = [
        "window",
        "test_return_pct",
        "test_max_dd_pct",
        "test_trades",
        "test_profit_factor",
    ]
    print(wf_df[display_cols].round(4).to_string(index=False))

    print("\n===== WALK-FORWARD AVERAGES =====")
    print(f"Avg Return [%]: {wf_df['test_return_pct'].mean():.5f}")
    print(f"Avg Max. Drawdown [%]: {wf_df['test_max_dd_pct'].mean():.5f}")
    print(f"Avg # Trades: {wf_df['test_trades'].mean():.2f}")
    print(f"Avg Profit Factor: {wf_df['test_profit_factor'].mean():.5f}")


def main():
    split_index = int(len(df) * 0.7)
    train_df = df.iloc[:split_index].copy()
    test_df = df.iloc[split_index:].copy()

    best_params, train_stats = optimize_train(train_df)

    print("\n===== BEST TRAIN PARAMS =====")
    for key, value in best_params.items():
        print(f"{key}: {value}")

    test_bt = Backtest(
        test_df,
        EMARSIMomentumStrategy,
        cash=100000,
        commission=0.001,
        exclusive_orders=True,
        finalize_trades=True
    )
    test_stats = test_bt.run(**best_params)

    print_core_metrics("IN-SAMPLE (70%)", train_stats)
    print_core_metrics("OUT-OF-SAMPLE (30%)", test_stats)

    wf_df = run_walk_forward(df)
    print_walk_forward_summary(wf_df)

    # Plot only the out-of-sample run for cleaner review.
    test_bt.plot()


if __name__ == "__main__":
    main()