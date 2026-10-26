
import os
import requests
from datetime import datetime, timezone, timedelta

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
API_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip()

PAIRS = [
    "EUR/JPY", "EUR/GBP", "CAD/JPY", "EUR/USD",
    "AUD/JPY", "AUD/USD", "AUD/CAD", "EUR/CAD",
    "USD/JPY", "EUR/AUD", "CHF/JPY", "GBP/AUD",
    "GBP/CAD", "EUR/CHF", "GBP/CHF", "GBP/JPY",
    "GBP/USD", "USD/CHF", "USD/CAD", "NZD/USD",
    "CAD/CHF", "AUD/CHF", "EUR/NZD", "NZD/CAD",
    "GBP/NZD", "AUD/NZD"
]

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


def get_candles(pair):
    response = requests.get(
        f"{BASE_URL}/time_series",
        params={
            "symbol": pair,
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
    return [float(c["close"]) for c in candles]


def ema(values, period):
    alpha = 2 / (period + 1)
    result = values[0]
    for value in values[1:]:
        result = alpha * value + (1 - alpha) * result
    return result


def get_signal(pair):
    closes = get_candles(pair)

    if len(closes) < 25:
        return "NO TRADE"

    fast = ema(closes[-30:], 9)
    slow = ema(closes[-30:], 21)

    if fast > slow:
        return "CALL"
    if fast < slow:
        return "PUT"
    return "NO TRADE"


def main():
    if not BOT_TOKEN or not CHAT_ID or not API_KEY:
        raise RuntimeError("GitHub Secrets missing.")

    messages = []

    for pair in PAIRS:
        try:
            signal = get_signal(pair)
            if signal == "NO TRADE":
                continue

            messages.append(
                f"{pair.replace('/', '/').title()}\n"
                f"Non Mtg Sureshot\n"
                f"Signal: {signal}"
            )

        except Exception as error:
            print(f"{pair}: {error}")

    now = datetime.now(
        timezone(timedelta(hours=6))
    ).strftime("%H:%M")

    if not messages:
        messages = ["No valid signals available right now."]

    send_telegram(
        f"REAL FOREX | {now}, +6 UTC\n\n"
        + "\n\n".join(messages)
        + "\n\nSignals are experimental, not guaranteed."
    )


if __name__ == "__main__":
    main()
