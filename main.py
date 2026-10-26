import os
import time
import requests
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# ===== SETTINGS =====
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip()

SYMBOL = "EUR/JPY"
INTERVAL = "1min"
TIMEZONE = ZoneInfo("Asia/Dhaka")
SIGNATURE = "ALAMIN SIGNAL 01883312072"

BASE_URL = "https://api.twelvedata.com/time_series"


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError(
            "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID secret."
        )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

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
        raise RuntimeError(
            f"Telegram API error: {result.get('description', 'unknown error')}"
        )


def get_candles(outputsize=150):
    if not TWELVE_DATA_API_KEY:
        raise RuntimeError("Missing TWELVE_DATA_API_KEY secret.")

    response = requests.get(
        BASE_URL,
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
    payload = response.json()

    if payload.get("status") == "error" or "values" not in payload:
        raise RuntimeError(
            f"Twelve Data API error: {payload.get('message', 'No candle data')}"
        )

    df = pd.DataFrame(payload["values"])

    if df.empty or "datetime" not in df.columns:
        raise RuntimeError("Market data is empty or missing timestamps.")

    for column in ["open", "high", "low", "close"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df["datetime"] = pd.to_datetime(
        df["datetime"], errors="coerce"
    )

    df = (
        df.dropna(subset=["datetime", "open", "high", "low", "close"])
        .drop_duplicates(subset=["datetime"])
        .sort_values("datetime")
        .reset_index(drop=True)
    )

    if len(df) < 2:
        raise RuntimeError("Not enough candles from market data.")

    return df


def calculate_rsi(series, period=14):
    delta = series.diff()

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

    relative_strength = avg_gain / avg_loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + relative_strength))

    return rsi.fillna(50)


def analyze():
    df = get_candles(outputsize=150)

    if len(df) < 50:
        raise RuntimeError("Not enough candles for signal analysis.")

    # Indicators are used internally only.
    df["ema9"] = df["close"].ewm(
        span=9, adjust=False
    ).mean()

    df["ema21"] = df["close"].ewm(
        span=21, adjust=False
    ).mean()

    df["rsi14"] = calculate_rsi(df["close"], 14)

    df["bb_mid"] = df["close"].rolling(20).mean()

    bb_std = df["close"].rolling(20).std(ddof=0)

    df["bb_upper"] = df["bb_mid"] + (2 * bb_std)
    df["bb_lower"] = df["bb_mid"] - (2 * bb_std)

    # Ignore the latest candle because it may still be forming.
    row = df.iloc[-2]

    call_score = 0
    put_score = 0

    if row["ema9"] > row["ema21"]:
        call_score += 1
    elif row["ema9"] < row["ema21"]:
        put_score += 1

    if row["rsi14"] >= 50:
        call_score += 1
    else:
        put_score += 1

    if row["close"] > row["bb_mid"]:
        call_score += 1
    elif row["close"] < row["bb_mid"]:
        put_score += 1

    # CALL or PUT only.
    if call_score > put_score:
        signal = "CALL"
    elif put_score > call_score:
        signal = "PUT"
    else:
        signal = "CALL" if row["ema9"] >= row["ema21"] else "PUT"

    now = datetime.now(TIMEZONE)

    # Entry at the next full minute.
    entry_time = (
        now.replace(second=0, microsecond=0)
        + timedelta(minutes=1)
    )

    return signal, entry_time


def find_entry_candle(entry_time):
    df = get_candles(outputsize=20)

    target = entry_time.replace(
        tzinfo=None,
        second=0,
        microsecond=0
    )

    matches = df[df["datetime"] == target]

    if matches.empty:
        return None

    return matches.iloc[-1]


def check_result(signal, entry_time):
    check_at = entry_time + timedelta(minutes=1, seconds=8)

    wait_seconds = (
        check_at - datetime.now(TIMEZONE)
    ).total_seconds()

    if wait_seconds > 0:
        time.sleep(wait_seconds)

    try:
        candle = find_entry_candle(entry_time)

        if candle is None:
            return "UNAVAILABLE"

        open_price = float(candle["open"])
        close_price = float(candle["close"])

        if close_price == open_price:
            return "DRAW"

        if signal == "CALL":
            return "PROFIT" if close_price > open_price else "LOSS"

        return "PROFIT" if close_price < open_price else "LOSS"

    except Exception as exc:
        print(f"Result check failed: {exc}")
        return "UNAVAILABLE"


def main():
    signal, entry_time = analyze()

    direction = "UP" if signal == "CALL" else "DOWN"

    signal_message = (
        f"{SYMBOL} ( REAL MARKET )\n"
        f"SIGNAL : {signal}\n"
        f"ENTRY TIME : {entry_time.strftime('%H:%M')}\n"
        f"TIMEFRAME : 1 MINUTE\n"
        f"DIRECTION : {direction}\n"
        f"{SIGNATURE}"
    )

    send_telegram(signal_message)
    print("Signal sent:", signal_message)

    result = check_result(signal, entry_time)

    result_message = (
        f"{SYMBOL} ( REAL MARKET )\n"
        f"RESULT : {result}\n"
        f"{SIGNATURE}"
    )

    send_telegram(result_message)
    print("Result sent:", result_message)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Bot error: {exc}")
        raise
