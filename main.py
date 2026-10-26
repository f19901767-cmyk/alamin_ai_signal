import os
import time
import requests
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# ================= SETTINGS =================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip()

SYMBOL = "EUR/JPY"
INTERVAL = "1min"
TZ = ZoneInfo("Asia/Dhaka")
SIGNATURE = "ALAMIN SIGNAL 01883312072"

API_URL = "https://api.twelvedata.com/time_series"


# ================= TELEGRAM =================

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("Telegram Secrets missing.")

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    response = requests.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message
        },
        timeout=20
    )

    response.raise_for_status()
    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(result.get("description", "Telegram error"))


# ================= MARKET DATA =================

def get_candles(outputsize=200):
    if not TWELVE_DATA_API_KEY:
        raise RuntimeError("Twelve Data API key missing.")

    response = requests.get(
        API_URL,
        params={
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "outputsize": outputsize,
            "timezone": "Asia/Dhaka",
            "apikey": TWELVE_DATA_API_KEY
        },
        timeout=25
    )

    response.raise_for_status()
    data = response.json()

    if data.get("status") == "error" or "values" not in data:
        raise RuntimeError(
            data.get("message", "Market data unavailable.")
        )

    df = pd.DataFrame(data["values"])

    if df.empty:
        raise RuntimeError("No market candles returned.")

    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["datetime"] = pd.to_datetime(
        df["datetime"], errors="coerce"
    )

    df = (
        df.dropna(
            subset=[
                "datetime", "open", "high", "low", "close"
            ]
        )
        .drop_duplicates(subset=["datetime"])
        .sort_values("datetime")
        .reset_index(drop=True)
    )

    if len(df) < 100:
        raise RuntimeError("Not enough candles for analysis.")

    return df


# ================= INDICATORS =================

def calculate_rsi(close, period=14):
    delta = close.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / period,
        min_periods=period,
        adjust=False
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        min_periods=period,
        adjust=False
    ).mean()

    rs = avg_gain / avg_loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))

    return rsi.fillna(50)


def calculate_adx(df, period=14):
    high = df["high"]
    low = df["low"]
    close = df["close"]

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = up_move.where(
        (up_move > down_move) & (up_move > 0), 0.0
    )

    minus_dm = down_move.where(
        (down_move > up_move) & (down_move > 0), 0.0
    )

    tr = pd.concat(
        [
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs()
        ],
        axis=1
    ).max(axis=1)

    atr = tr.ewm(
        alpha=1 / period, adjust=False
    ).mean()

    plus_di = (
        100 * plus_dm.ewm(
            alpha=1 / period, adjust=False
        ).mean() / atr.replace(0, float("nan"))
    )

    minus_di = (
        100 * minus_dm.ewm(
            alpha=1 / period, adjust=False
        ).mean() / atr.replace(0, float("nan"))
    )

    dx = (
        100 * (plus_di - minus_di).abs()
        / (plus_di + minus_di).replace(0, float("nan"))
    )

    adx = dx.ewm(
        alpha=1 / period, adjust=False
    ).mean()

    return plus_di.fillna(0), minus_di.fillna(0), adx.fillna(0)


def calculate_psar(df, step=0.02, maximum=0.2):
    high = df["high"].tolist()
    low = df["low"].tolist()

    psar = [low[0]] * len(df)
    bullish = True
    extreme = high[0]
    acceleration = step

    for i in range(1, len(df)):
        previous = psar[i - 1]

        if bullish:
            current = previous + acceleration * (
                extreme - previous
            )
            current = min(current, low[i - 1])

            if i >= 2:
                current = min(current, low[i - 2])

            if low[i] < current:
                bullish = False
                current = extreme
                extreme = low[i]
                acceleration = step
            elif high[i] > extreme:
                extreme = high[i]
                acceleration = min(
                    acceleration + step, maximum
                )

        else:
            current = previous + acceleration * (
                extreme - previous
            )
            current = max(current, high[i - 1])

            if i >= 2:
                current = max(current, high[i - 2])

            if high[i] > current:
                bullish = True
                current = extreme
                extreme = high[i]
                acceleration = step
            elif low[i] < extreme:
                extreme = low[i]
                acceleration = min(
                    acceleration + step, maximum
                )

        psar[i] = current

    return pd.Series(psar, index=df.index)


# ================= ANALYSIS =================

def analyze():
    df = get_candles(200)

    # Exclude the newest candle because it may still be forming.
    df = df.iloc[:-1].copy().reset_index(drop=True)

    if len(df) < 100:
        raise RuntimeError("Not enough completed candles.")

    close = df["close"]
    high = df["high"]
    low = df["low"]
    open_price = df["open"]

    # Trend
    df["ema9"] = close.ewm(span=9, adjust=False).mean()
    df["ema21"] = close.ewm(span=21, adjust=False).mean()
    df["ema50"] = close.ewm(span=50, adjust=False).mean()
    df["ema200"] = close.ewm(span=200, adjust=False).mean()

    # RSI
    df["rsi"] = calculate_rsi(close, 14)

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()

    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(
        span=9, adjust=False
    ).mean()

    # Bollinger Bands
    df["bb_mid"] = close.rolling(20).mean()
    bb_std = close.rolling(20).std(ddof=0)

    df["bb_upper"] = df["bb_mid"] + 2 * bb_std
    df["bb_lower"] = df["bb_mid"] - 2 * bb_std

    # Stochastic oscillator
    lowest = low.rolling(14).min()
    highest = high.rolling(14).max()

    df["stoch_k"] = (
        100 * (close - lowest)
        / (highest - lowest).replace(0, float("nan"))
    )

    df["stoch_d"] = df["stoch_k"].rolling(3).mean()

    # ATR
    tr = pd.concat(
        [
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs()
        ],
        axis=1
    ).max(axis=1)

    df["atr"] = tr.ewm(
        alpha=1 / 14, adjust=False
    ).mean()

    # ADX and directional movement
    df["plus_di"], df["minus_di"], df["adx"] = (
        calculate_adx(df, 14)
    )

    # CCI
    typical = (high + low + close) / 3
    typical_mean = typical.rolling(20).mean()

    mean_deviation = typical.rolling(20).apply(
        lambda x: abs(x - x.mean()).mean(),
        raw=True
    )

    df["cci"] = (
        (typical - typical_mean)
        / (0.015 * mean_deviation).replace(0, float("nan"))
    )

    # Williams %R
    df["williams"] = (
        -100 * (highest - close)
        / (highest - lowest).replace(0, float("nan"))
    )

    # Parabolic SAR
    df["psar"] = calculate_psar(df)

    row = df.iloc[-1]
    prev = df.iloc[-2]

    call_score = 0
    put_score = 0

    # EMA trend
    if row["ema9"] > row["ema21"]:
        call_score += 2
    else:
        put_score += 2

    if row["ema21"] > row["ema50"]:
        call_score += 2
    else:
        put_score += 2

    if row["ema50"] > row["ema200"]:
        call_score += 2
    else:
        put_score += 2

    # RSI
    if row["rsi"] > 55:
        call_score += 1
    elif row["rsi"] < 45:
        put_score += 1

    # MACD
    if row["macd"] > row["macd_signal"]:
        call_score += 2
    else:
        put_score += 2

    # Bollinger middle line
    if row["close"] > row["bb_mid"]:
        call_score += 1
    else:
        put_score += 1

    # Stochastic
    if row["stoch_k"] > row["stoch_d"]:
        call_score += 1
    else:
        put_score += 1

    # ADX directional trend
    if row["adx"] >= 20:
        if row["plus_di"] > row["minus_di"]:
            call_score += 2
        elif row["minus_di"] > row["plus_di"]:
            put_score += 2

    # CCI
    if row["cci"] > 0:
        call_score += 1
    else:
        put_score += 1

    # Williams %R
    if row["williams"] > -50:
        call_score += 1
    else:
        put_score += 1

    # Parabolic SAR
    if row["close"] > row["psar"]:
        call_score += 1
    else:
        put_score += 1

    # Candle momentum
    if row["close"] > row["open"]:
        call_score += 1
    elif row["close"] < row["open"]:
        put_score += 1

    # Previous candle movement
    if row["close"] > prev["close"]:
        call_score += 1
    elif row["close"] < prev["close"]:
        put_score += 1

    # Support and resistance: recent 20-candle levels
    recent = df.iloc[-21:-1]
    support = recent["low"].min()
    resistance = recent["high"].max()

    if row["close"] > (support + resistance) / 2:
        call_score += 1
    elif row["close"] < (support + resistance) / 2:
        put_score += 1

    # Basic candlestick body confirmation
    body = abs(row["close"] - row["open"])
    candle_range = row["high"] - row["low"]

    if candle_range > 0 and body / candle_range >= 0.5:
        if row["close"] > row["open"]:
            call_score += 1
        elif row["close"] < row["open"]:
            put_score += 1

    # ATR is used to assess volatility; it does not predict direction.
    if pd.isna(row["atr"]) or row["atr"] <= 0:
        raise RuntimeError("Volatility data unavailable.")

    # Always return CALL or PUT, as requested.
    if call_score > put_score:
        signal = "CALL"
    elif put_score > call_score:
        signal = "PUT"
    else:
        signal = (
            "CALL"
            if row["ema9"] >= row["ema21"]
            else "PUT"
        )

    now = datetime.now(TZ)
    entry_time = (
        now.replace(second=0, microsecond=0)
        + timedelta(minutes=1)
    )

    return signal, entry_time


# ================= RESULT CHECK =================

def find_entry_candle(entry_time):
    df = get_candles(20)

    target = entry_time.replace(
        tzinfo=None, second=0, microsecond=0
    )

    matches = df[df["datetime"] == target]

    if matches.empty:
        return None

    return matches.iloc[-1]


def check_result(signal, entry_time):
    check_at = entry_time + timedelta(minutes=1, seconds=8)

    wait_seconds = (
        check_at - datetime.now(TZ)
    ).total_seconds()

    if wait_seconds > 0:
        time.sleep(wait_seconds)

    try:
        candle = find_entry_candle(entry_time)

        if candle is None:
            return "UNAVAILABLE"

        op = float(candle["open"])
        cl = float(candle["close"])

        if cl == op:
            return "DRAW"

        if signal == "CALL":
            return "PROFIT" if cl > op else "LOSS"

        return "PROFIT" if cl < op else "LOSS"

    except Exception as exc:
        print(f"Result check error: {exc}")
        return "UNAVAILABLE"


# ================= RUN BOT =================

def main():
    signal, entry_time = analyze()

    direction = "UP" if signal == "CALL" else "DOWN"

    message = (
        f"{SYMBOL} ( REAL MARKET )\n"
        f"SIGNAL : {signal}\n"
        f"ENTRY TIME : {entry_time.strftime('%H:%M')}\n"
        f"TIMEFRAME : 1 MINUTE\n"
        f"DIRECTION : {direction}\n"
        f"{SIGNATURE}"
    )

    send_telegram(message)
    print("Signal sent.")

    result = check_result(signal, entry_time)

    result_message = (
        f"{SYMBOL} ( REAL MARKET )\n"
        f"RESULT : {result}\n"
        f"{SIGNATURE}"
    )

    send_telegram(result_message)
    print("Result sent:", result)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"BOT ERROR: {exc}")
        raise
