
import os
import requests
from datetime import datetime, timezone, timedelta

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
API_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip()

SYMBOL = "EUR/USD"
BASE_URL = "https://api.twelvedata.com"


def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    response = requests.post(
        url,
        json={"chat_id": CHAT_ID, "text": message},
        timeout=20
    )
    response.raise_for_status()
    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(str(result))


def get_signal():
    response = requests.get(
        f"{BASE_URL}/time_series",
        params={
            "symbol": SYMBOL,
            "interval": "1min",
            "outputsize": 40,
            "apikey": API_KEY
        },
        timeout=20
    )
    data = response.json()

    if "values" not in data:
        raise RuntimeError(
            str(data.get("message", "Market data unavailable"))
        )

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

    fast = ema(closes[-30:], 9)
    slow = ema(closes[-30:], 21)

    if fast > slow:
        return "Go For Up"
    if fast < slow:
        return "Go For Down"
    return "NO TRADE"


def main():
    if not BOT_TOKEN or not CHAT_ID or not API_KEY:
        raise RuntimeError("Check GitHub Secrets.")

    signal = get_signal()
    local_time = datetime.now(
        timezone(timedelta(hours=6))
    ).strftime("%H:%M")

    message = (
        "Eur/Usd\n"
        f"{local_time}, +6 UTC\n"
        f"{signal}\n"
        "Non Mtg"
    )

    send_telegram(message)
    print(message)


if __name__ == "__main__":
    main()
