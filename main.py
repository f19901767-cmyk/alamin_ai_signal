
import os
import requests

API_KEY = os.environ["TWELVE_DATA_API_KEY"]
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    response = requests.post(
        url,
        data={"chat_id": CHAT_ID, "text": message},
        timeout=15
    )
    response.raise_for_status()

def get_signal():
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": "EUR/JPY",
        "interval": "1min",
        "outputsize": 60,
        "apikey": API_KEY
    }

    response = requests.get(url, params=params, timeout=20)
    response.raise_for_status()
    data = response.json()

    if "values" not in data:
        raise RuntimeError(data.get("message", "Market data unavailable"))

    candles = list(reversed(data["values"]))
    closes = [float(c["close"]) for c in candles]

    if len(closes) < 25:
        return "NO TRADE"

    def ema(values, period):
        alpha = 2 / (period + 1)
        result = values[0]
        for value in values[1:]:
            result = alpha * value + (1 - alpha) * result
        return result

    ema9 = ema(closes[-30:], 9)
    ema21 = ema(closes[-50:], 21)

    if ema9 > ema21 and closes[-1] > ema9:
        return "CALL"
    elif ema9 < ema21 and closes[-1] < ema9:
        return "PUT"
    return "NO TRADE"

if __name__ == "__main__":
    signal = get_signal()
    message = (
        "EUR/JPY\n"
        f"{signal}\n"
        "Timeframe: 1 Minute\n"
        "Market: Real Forex\n"
        "Strategy: EMA 9/21"
    )
    send_telegram(message)
