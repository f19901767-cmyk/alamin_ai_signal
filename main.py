
import os
import time
import requests
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# ===== SETTINGS =====
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
API_KEY = os.environ["TWELVE_DATA_API_KEY"]

TIMEZONE = ZoneInfo("Asia/Dhaka")
SYMBOL = "EUR/JPY"
TIMEFRAME = "1min"


def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    response = requests.post(
        url,
        data={"chat_id": CHAT_ID, "text": message},
        timeout=20,
    )
    response.raise_for_status()
    if not response.json().get("ok"):
        raise RuntimeError("Telegram message failed.")


def get_candles(outputsize=150):
    response = requests.get(
        "https://api.twelvedata.com/time_series",
        params={
            "symbol": SYMBOL,
            "interval": TIMEFRAME,
            "outputsize": outputsize,
            "apikey": API_KEY,
            "format": "JSON",
            "timezone": "Asia/Dhaka",
        },
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()

    if "values" not in data:
        raise RuntimeError(
            "Market data error: " + str(data.get("message", data))
        )

    df = pd.DataFrame(data["values"])
    df["datetime"] = pd.to_datetime(
        df["datetime"], errors="coerce"
    )

    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = (
        df.dropna(subset=["datetime", "open", "high", "low", "close"])
        .sort_values("datetime")
        .drop_duplicates("datetime")
        .reset_index(drop=True)
    )

    if len(df) < 50:
        raise RuntimeError("Not enough candles for analysis.")

    return df


def analyze():
    df = get_candles()
    close = df["close"]

    # EMA 9 and EMA 21
    df["ema9"] = close.ewm(span=9, adjust=False).mean()
    df["ema21"] = close.ewm(span=21, adjust=False).mean()

    # RSI 14
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / 14, min_periods=14, adjust=False
    ).mean()
    avg_loss = loss.ewm(
        alpha=1 / 14, min_periods=14, adjust=False
    ).mean()

    rs = avg_gain / avg_loss.replace(0, float("nan"))
    df["rsi"] = (100 - (100 / (1 + rs))).fillna(50)

    # Bollinger Bands (20, 2)
    df["bb_mid"] = close.rolling(20).mean()
    std = close.rolling(20).std(ddof=0)
    df["bb_upper"] = df["bb_mid"] + 2 * std
    df["bb_lower"] = df["bb_mid"] - 2 * std

    # Use a completed candle only
    now = datetime.now(TIMEZONE)
    current_minute = now.replace(second=0, microsecond=0)
    latest = df.iloc[-1]["datetime"]

    if latest == current_minute.replace(tzinfo=None):
        df = df.iloc[:-1].copy()

    last = df.iloc[-1]
    previous = df.iloc[-2]

    call_score = 0
    put_score = 0

    # EMA trend and crossover
    if last["ema9"] > last["ema21"]:
        call_score += 2
    elif last["ema9"] < last["ema21"]:
        put_score += 2

    if previous["ema9"] <= previous["ema21"] and last["ema9"] > last["ema21"]:
        call_score += 1

    if previous["ema9"] >= previous["ema21"] and last["ema9"] < last["ema21"]:
        put_score += 1

    # RSI
    rsi = float(last["rsi"])

    if 50 < rsi < 70:
        call_score += 2
    elif 30 < rsi < 50:
        put_score += 2
    elif rsi >= 70:
        put_score += 1
    elif rsi <= 30:
        call_score += 1

    # Bollinger Bands
    price = float(last["close"])

    if price > last["bb_mid"]:
        call_score += 1
    elif price < last["bb_mid"]:
        put_score += 1

    if price <= last["bb_lower"]:
        call_score += 1

    if price >= last["bb_upper"]:
        put_score += 1

    # Always CALL or PUT
    if call_score > put_score:
        signal, direction = "CALL", "UP"
    elif put_score > call_score:
        signal, direction = "PUT", "DOWN"
    elif last["ema9"] >= last["ema21"]:
        signal, direction = "CALL", "UP"
    else:
        signal, direction = "PUT", "DOWN"

    entry = (datetime.now(TIMEZONE) + timedelta(minutes=1))
    entry = entry.replace(second=0, microsecond=0)

    message = (
        "EUR/JPY ( REAL MARKET )\n"
        f"SIGNAL : {signal}\n"
        f"ENTRY TIME : {entry.strftime('%H:%M')}\n"
        "TIMEFRAME : 1 MINUTE\n"
        f"DIRECTION : {direction}\n"
        "ALAMIN SIGNAL 01883312072"
    )

    return signal, entry, message


def find_entry_candle(entry_time):
    target = entry_time.replace(tzinfo=None, second=0, microsecond=0)

    for _ in range(6):
        df = get_candles(outputsize=20)
        stamps = df["datetime"]

        match = df[
            (stamps.dt.year == target.year)
            & (stamps.dt.month == target.month)
            & (stamps.dt.day == target.day)
            & (stamps.dt.hour == target.hour)
            & (stamps.dt.minute == target.minute)
        ]

        if not match.empty:
            return match.iloc[-1]

        time.sleep(10)

    return None


def check_result(signal, entry_time):
    # Wait until the entry minute has closed
    expiry = entry_time + timedelta(minutes=1)
    wait = (expiry - datetime.now(TIMEZONE)).total_seconds()

    if wait > 0:
        time.sleep(wait)

    # Allow market data time to update
    time.sleep(8)

    candle = find_entry_candle(entry_time)

    if candle is None:
        result = "UNAVAILABLE"
    else:
        open_price = float(candle["open"])
        close_price = float(candle["close"])

        if close_price == open_price:
            result = "DRAW"
        elif signal == "CALL":
            result = "PROFIT" if close_price > open_price else "LOSS"
        else:
            result = "PROFIT" if close_price < open_price else "LOSS"

    send_telegram(
        "EUR/JPY ( REAL MARKET )\n"
        f"SIGNAL : {signal}\n"
        f"ENTRY TIME : {entry_time.strftime('%H:%M')}\n"
        "TIMEFRAME : 1 MINUTE\n"
        f"RESULT : {result}\n"
        "ALAMIN SIGNAL 01883312072"
    )


if __name__ == "__main__":
    try:
        signal, entry_time, message = analyze()
        send_telegram(message)
        print("Signal sent. Waiting for result...")
        check_result(signal, entry_time)
        print("Result message sent.")
    except Exception as error:
        print(f"Error: {error}")
        raise
