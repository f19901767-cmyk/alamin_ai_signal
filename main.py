
import os
import requests
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
API_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip()

SYMBOLS = ["EUR/USD", "GBP/USD", "USD/JPY"]
BASE_URL = "https://api.twelvedata.com"


def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError(
            "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID secret."
        )

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    response = requests.post(
        url,
        json={
            "chat_id": CHAT_ID,
            "text": text
        },
        timeout=20
    )

    if not response.ok:
        raise RuntimeError(
            f"Telegram API error {response.status_code}: "
            f"{response.text}"
        )

    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram rejected message: {result}")

    print("Telegram message sent successfully.")


def get_candles(symbol):
    if not API_KEY:
        raise RuntimeError("Missing TWELVE_DATA_API_KEY secret.")

    response = requests.get(
        f"{BASE_URL}/time_series",
        params={
            "symbol": symbol,
            "interval": "1min",
            "outputsize": 40,
            "apikey": API_KEY
        },
        timeout=25
    )

    data = response.json()

    if not response.ok or "values" not in data:
        message = data.get("message", data.get("code", response.text))
        raise RuntimeError(f"Twelve Data error for {symbol}: {message}")

    candles = data["values"]

    if len(candles) < 25:
        raise RuntimeError(
            f"Not enough 1-minute candles for {symbol}."
        )

    # Twelve Data returns newest candle first.
    candles.reverse()

    return [float(candle["close"]) for candle in candles]


def ema(values, period):
    alpha = 2 / (period + 1)
    result = values[0]

    for value in values[1:]:
        result = alpha * value + (1 - alpha) * result

    return result


def calculate_rsi(values, period=14):
    changes = [
        values[i] - values[i - 1]
        for i in range(1, len(values))
    ]

    recent = changes[-period:]
    gains = [max(change, 0) for change in recent]
    losses = [max(-change, 0) for change in recent]

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def analyze(symbol):
    closes = get_candles(symbol)

    fast = ema(closes[-30:], 9)
    slow = ema(closes[-30:], 21)
    rsi = calculate_rsi(closes)

    if fast > slow and 52 <= rsi <= 68:
        signal = "CALL"
    elif fast < slow and 32 <= rsi <= 48:
        signal = "PUT"
    else:
        signal = "NO TRADE"

    return (
        f"{symbol}: {signal}\n"
        f"Price: {closes[-1]}\n"
        f"EMA9: {fast:.5f} | EMA21: {slow:.5f}\n"
        f"RSI14: {rsi:.1f}"
    )


def main():
    messages = [
        "Alamin Signal Bot",
        "Timeframe: 1 minute",
        "Source: Twelve Data (not Quotex OTC)",
        "Signals are experimental, not guaranteed.",
        ""
    ]

    for symbol in SYMBOLS:
        try:
            messages.append(analyze(symbol))
        except Exception as error:
            print(f"Analysis failed for {symbol}: {error}")
            messages.append(f"{symbol}: NO TRADE (data/error)")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    messages.append(f"\nUpdated: {now}")

    send_telegram("\n".join(messages))


if __name__ == "__main__":
    main()
