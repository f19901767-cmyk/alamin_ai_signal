
import os
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


def get_candles():
    url = "https://api.twelvedata.com/time_series"

    response = requests.get(
        url,
        params={
            "symbol": SYMBOL,
            "interval": "1min",
            "outputsize": 150,
            "apikey": API_KEY,
            "format": "JSON"
        },
        timeout=20
    )
    response.raise_for_status()
    data = response.json()

    if "values" not in data:
        raise RuntimeError(
            "Market data error: " +
            str(data.get("message", data))
        )

    df = pd.DataFrame(data["values"])
    df["datetime"] = pd.to_datetime(df["datetime"])

    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = (
        df.dropna()
        .sort_values("datetime")
        .drop_duplicates("datetime")
        .reset_index(drop=True)
    )

    # Exclude the newest candle because it may still be forming.
    if len(df) > 1:
        df = df.iloc[:-1].copy()

    if len(df) < 50:
        raise RuntimeError("Not enough candles for analysis.")

    return df


def analyze():
    df = get_candles()
    close = df["close"]

    # EMA 9 and EMA 21
    df["ema9"] = close.ewm(
        span=9, adjust=False
    ).mean()

    df["ema21"] = close.ewm(
        span=21, adjust=False
    ).mean()

    # RSI 14
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1/14, min_periods=14, adjust=False
    ).mean()

    avg_loss = loss.ewm(
        alpha=1/14, min_periods=14, adjust=False
    ).mean()

    rs = avg_gain / avg_loss.replace(0, float("nan"))
    df["rsi"] = 100 - (100 / (1 + rs))
    df["rsi"] = df["rsi"].fillna(50)

    # Bollinger Bands (20, 2)
    df["bb_mid"] = close.rolling(20).mean()
    std = close.rolling(20).std(ddof=0)

    df["bb_upper"] = df["bb_mid"] + (2 * std)
    df["bb_lower"] = df["bb_mid"] - (2 * std)

    last = df.iloc[-1]
    previous = df.iloc[-2]

    call_score = 0
    put_score = 0
    reasons_call = []
    reasons_put = []

    # EMA trend and crossover direction
    if last["ema9"] > last["ema21"]:
        call_score += 2
        reasons_call.append("EMA 9 > EMA 21")
    elif last["ema9"] < last["ema21"]:
        put_score += 2
        reasons_put.append("EMA 9 < EMA 21")

    if (
        previous["ema9"] <= previous["ema21"]
        and last["ema9"] > last["ema21"]
    ):
        call_score += 1
        reasons_call.append("EMA bullish crossover")

    if (
        previous["ema9"] >= previous["ema21"]
        and last["ema9"] < last["ema21"]
    ):
        put_score += 1
        reasons_put.append("EMA bearish crossover")

    # RSI 14: momentum without chasing extreme readings
    rsi = float(last["rsi"])

    if 50 < rsi < 70:
        call_score += 2
        reasons_call.append(f"RSI bullish ({rsi:.1f})")
    elif 30 < rsi < 50:
        put_score += 2
        reasons_put.append(f"RSI bearish ({rsi:.1f})")
    elif rsi >= 70:
        put_score += 1
        reasons_put.append(f"RSI overbought ({rsi:.1f})")
    elif rsi <= 30:
        call_score += 1
        reasons_call.append(f"RSI oversold ({rsi:.1f})")

    # Bollinger Bands position
    price = float(last["close"])

    if price > last["bb_mid"]:
        call_score += 1
        reasons_call.append("Price above BB middle")
    elif price < last["bb_mid"]:
        put_score += 1
        reasons_put.append("Price below BB middle")

    if price <= last["bb_lower"]:
        call_score += 1
        reasons_call.append("Near/below lower BB")

    if price >= last["bb_upper"]:
        put_score += 1
        reasons_put.append("Near/above upper BB")

    # Always choose CALL or PUT; no NO TRADE message.
    if call_score > put_score:
        signal = "CALL"
        direction = "UP"
        reason = ", ".join(reasons_call) or "Combined indicator score"
    elif put_score > call_score:
        signal = "PUT"
        direction = "DOWN"
        reason = ", ".join(reasons_put) or "Combined indicator score"
    else:
        # Tie-break using EMA trend
        if last["ema9"] >= last["ema21"]:
            signal = "CALL"
            direction = "UP"
            reason = "Score tie; EMA trend tie-break"
        else:
            signal = "PUT"
            direction = "DOWN"
            reason = "Score tie; EMA trend tie-break"

    # Next minute in Bangladesh time
    now = datetime.now(TIMEZONE)
    entry = (now + timedelta(minutes=1)).replace(
        second=0, microsecond=0
    )

    message = (
        f"EUR/JPY ( REAL MARKET )\n"
        f"SIGNAL : {signal}\n"
        f"ENTRY TIME : {entry.strftime('%H:%M')}\n"
        f"TIMEFRAME : 1 MINUTE\n"
        f"DIRECTION : {direction}\n"
        f"ANALYSIS : {reason}\n"
        f"ALAMIN SIGNAL 01883312072"
    )

    return message


def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    response = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": message
        },
        timeout=20
    )
    response.raise_for_status()

    result = response.json()
    if not result.get("ok"):
        raise RuntimeError("Telegram message failed.")


if __name__ == "__main__":
    try:
        signal_message = analyze()
        send_telegram(signal_message)
        print("Signal sent successfully.")
    except Exception as error:
        print(f"Signal error: {error}")
        raise
