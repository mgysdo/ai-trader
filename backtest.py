import pandas as pd

from backtesting import Backtest
from backtesting import Strategy

from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange


# =========================================================
# LOAD DATA
# =========================================================

df = pd.read_csv("btc_usdt_1h.csv")

df["timestamp"] = pd.to_datetime(df["timestamp"])

df.set_index("timestamp", inplace=True)

# Rename columns for backtesting.py
df.rename(
    columns={
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume"
    },
    inplace=True
)

df = df[
    [
        "Open",
        "High",
        "Low",
        "Close",
        "Volume"
    ]
]

df = df.dropna()


# =========================================================
# INDICATORS
# =========================================================

def add_indicators(dataframe):

    dataframe["ema_fast"] = EMAIndicator(
        close=dataframe["Close"],
        window=20
    ).ema_indicator()

    dataframe["ema_slow"] = EMAIndicator(
        close=dataframe["Close"],
        window=50
    ).ema_indicator()

    dataframe["rsi"] = RSIIndicator(
        close=dataframe["Close"],
        window=14
    ).rsi()

    dataframe["atr"] = AverageTrueRange(
        high=dataframe["High"],
        low=dataframe["Low"],
        close=dataframe["Close"],
        window=14
    ).average_true_range()

    return dataframe


df = add_indicators(df)

df = df.dropna()


# =========================================================
# STRATEGY
# =========================================================

class EMARSIMomentumStrategy(Strategy):

    risk_reward_ratio = 2

    def init(self):

        self.last_trade_bar = -100

    def next(self):

        current_bar = len(self.data.Close)

        cooldown_bars = 12

        if current_bar - self.last_trade_bar < cooldown_bars:
            return

        current_price = self.data.Close[-1]

        ema_fast = self.data.ema_fast[-1]
        ema_slow = self.data.ema_slow[-1]

        previous_ema_fast = self.data.ema_fast[-2]
        previous_ema_slow = self.data.ema_slow[-2]

        rsi = self.data.rsi[-1]

        atr = self.data.atr[-1]

        # =====================================================
        # TREND CONDITIONS
        # =====================================================

        bullish_trend = (
            previous_ema_fast <= previous_ema_slow
            and ema_fast > ema_slow
        )

        bearish_trend = (
            previous_ema_fast >= previous_ema_slow
            and ema_fast < ema_slow
        )

        # =====================================================
        # MOMENTUM FILTER
        # =====================================================

        bullish_momentum = (
            rsi > 55
            and rsi < 70
        )

        bearish_momentum = (
            rsi < 45
            and rsi > 30
        )

        # =====================================================
        # BUY
        # =====================================================

        if bullish_trend and bullish_momentum:

            if not self.position:

                stop_loss = current_price - (atr * 1.5)

                risk = current_price - stop_loss

                take_profit = current_price + (
                    risk * self.risk_reward_ratio
                )

                cash_risk = self.equity * 0.01

                position_size = cash_risk / risk

                position_size = max(
                    1,
                    int(position_size)
                )

                self.buy(
                    size=position_size,
                    sl=stop_loss,
                    tp=take_profit
                )

                self.last_trade_bar = current_bar

        # =====================================================
        # SELL
        # =====================================================

        if bearish_trend and bearish_momentum:

            if not self.position:

                stop_loss = current_price + (atr * 1.5)

                risk = stop_loss - current_price

                take_profit = current_price - (
                    risk * self.risk_reward_ratio
                )

                cash_risk = self.equity * 0.01

                position_size = cash_risk / risk

                position_size = max(
                    1,
                    int(position_size)
                )

                self.sell(
                    size=position_size,
                    sl=stop_loss,
                    tp=take_profit
                )

                self.last_trade_bar = current_bar


# =========================================================
# BACKTEST
# =========================================================

bt = Backtest(
    df,
    EMARSIMomentumStrategy,
    cash=100000,
    commission=0.0005,
    margin=1,
    trade_on_close=True,
    exclusive_orders=True,
    finalize_trades=True
)

stats = bt.run()

print(stats)

bt.plot()