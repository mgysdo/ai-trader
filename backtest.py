from binance.client import Client
import pandas as pd
import pandas_ta as ta
from backtesting import Backtest, Strategy

API_KEY = "NVXqXapN5RE5NmEX9tJ4RjDALMAoAOZFXQ90vSzgdk12qmKYCv81OAlQbYI4RV6q"
API_SECRET = "3qGBW7YvHq0HwYxxOGHcL0mESZRVbNkc17PjUi8TcMcOJuTmJbm5HHjnvn9qGXhd"

client = Client(API_KEY, API_SECRET)


# Fetch historical candles
klines = client.get_klines(
    symbol="BTCUSDT",
    interval=Client.KLINE_INTERVAL_5MINUTE,
    limit=2000
)

# Dataframe columns
columns = [
    "OpenTime",
    "Open",
    "High",
    "Low",
    "Close",
    "Volume",
    "CloseTime",
    "QuoteAssetVolume",
    "NumberOfTrades",
    "TakerBuyBaseAssetVolume",
    "TakerBuyQuoteAssetVolume",
    "Ignore"
]

# Create dataframe
df = pd.DataFrame(klines, columns=columns)

# Convert required columns
price_columns = [
    "Open",
    "High",
    "Low",
    "Close",
    "Volume"
]

for col in price_columns:
    df[col] = df[col].astype(float)

# Convert timestamp
df["OpenTime"] = pd.to_datetime(df["OpenTime"], unit="ms")

# Set index
df.set_index("OpenTime", inplace=True)

# Indicators
df["EMA20"] = ta.ema(df["Close"], length=20)
df["EMA50"] = ta.ema(df["Close"], length=50)

df["RSI"] = ta.rsi(df["Close"], length=14)

df["VOLUME_MA20"] = ta.sma(df["Volume"], length=20)

df["ATR"] = ta.atr(
    high=df["High"],
    low=df["Low"],
    close=df["Close"],
    length=14
)

# Drop NaN rows
df.dropna(inplace=True)


class EMARSIMomentumStrategy(Strategy):

    def init(self):
        pass

    def next(self):

        # Current candle
        price = self.data.Close[-1]

        ema20 = self.data.EMA20[-1]
        ema50 = self.data.EMA50[-1]

        rsi = self.data.RSI[-1]

        volume = self.data.Volume[-1]
        volume_ma20 = self.data.VOLUME_MA20[-1]

        atr = self.data.ATR[-1]

        # Filters
        volume_confirmed = (
            volume > volume_ma20 * 0.8
        )

        atr_confirmed = (
            atr > price * 0.002
        )

        # Confidence scoring
        confidence = 0

        # EMA gap strength
        ema_gap_percent = (
            abs(ema20 - ema50)
            / price
        ) * 100

        # RSI quality
        if 55 <= rsi <= 65:
            confidence += 25

        elif 50 <= rsi <= 70:
            confidence += 15

        # Volume quality
        volume_ratio = (
            volume / volume_ma20
        )

        if volume_ratio >= 1.5:
            confidence += 25

        elif volume_ratio >= 1.0:
            confidence += 15

        # ATR quality
        atr_percent = (
            atr / price
        ) * 100

        if atr_percent >= 0.5:
            confidence += 25

        elif atr_percent >= 0.2:
            confidence += 15

        # EMA separation
        if ema_gap_percent >= 0.5:
            confidence += 25

        elif ema_gap_percent >= 0.2:
            confidence += 15

        # Avoid multiple positions
        if self.position:
            return

        # LONG setup
        if (
            ema20 > ema50
            and 50 <= rsi <= 70
            and volume_confirmed
            and atr_confirmed
            and confidence >= 60
        ):

            stop_distance = atr * 1.5

            stop_loss = (
                price - stop_distance
            )

            take_profit = (
                price + (stop_distance * 2)
            )

            self.buy(
                sl=stop_loss,
                tp=take_profit
            )

        # SHORT setup
        elif (
            ema20 < ema50
            and 30 <= rsi <= 50
            and volume_confirmed
            and atr_confirmed
            and confidence >= 60
        ):

            stop_distance = atr * 1.5

            stop_loss = (
                price + stop_distance
            )

            take_profit = (
                price - (stop_distance * 2)
            )

            self.sell(
                sl=stop_loss,
                tp=take_profit
            )


# Run backtest
bt = Backtest(
    df,
    EMARSIMomentumStrategy,
    cash=10000,
    commission=0.001,
    exclusive_orders=True
)

stats = bt.run()

# Print results
print(stats)

# Show chart
bt.plot()