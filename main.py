import os
import requests
from datetime import datetime, timezone

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
API_KEY = os.environ["TWELVE_DATA_API_KEY"]
SYMBOLS = [x.strip() for x in os.getenv("SYMBOLS", "EUR/USD,GBP/USD").split(",") if x.strip()]

def send_telegram(text):
    r = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text}, timeout=20
    )
    r.raise_for_status()
    if not r.json().get("ok"):
        raise RuntimeError("Telegram API did not accept the message")

def get_candles(symbol):
    r = requests.get("https://api.twelvedata.com/time_series", params={
        "symbol": symbol, "interval": "1min", "outputsize": 60,
        "apikey": API_KEY, "timezone": "UTC", "order": "desc"
    }, timeout=20)
    r.raise_for_status()
    data = r.json()
    if "values" not in data:
        raise RuntimeError(data.get("message", "No candle data returned"))
    return list(reversed(data["values"]))

def ema(values, period):
    alpha = 2 / (period + 1)
    result = values[0]
    for value in values[1:]:
        result = alpha * value + (1 - alpha) * result
    return result

def rsi(values, period=14):
    changes = [values[i] - values[i-1] for i in range(1, len(values))][-period:]
    if len(changes) < period:
        return 50.0
    gains = sum(max(x, 0) for x in changes) / period
    losses = sum(max(-x, 0) for x in changes) / period
    if losses == 0:
        return 100.0
    rs = gains / losses
    return 100 - (100 / (1 + rs))

def analyse(candles):
    if len(candles) < 35:
        return "NO TRADE", "পর্যাপ্ত ক্যান্ডেল নেই"
    closes = [float(c["close"]) for c in candles[:-1]]  # exclude forming candle
    fast, slow = ema(closes[-30:], 9), ema(closes[-30:], 21)
    momentum = rsi(closes, 14)
    if fast > slow and 52 <= momentum <= 68:
        return "CALL", f"EMA9 > EMA21; RSI={momentum:.1f}"
    if fast < slow and 32 <= momentum <= 48:
        return "PUT", f"EMA9 < EMA21; RSI={momentum:.1f}"
    return "NO TRADE", f"পরিষ্কার সেটআপ নেই; RSI={momentum:.1f}"

def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    messages = [f"📊 Alamin Forex Signal (পরীক্ষামূলক)\nসময়: {now}"]
    for symbol in SYMBOLS:
        try:
            signal, reason = analyse(get_candles(symbol))
            messages.append(f"\n{symbol}\nসিগন্যাল: {signal}\nকারণ: {reason}")
        except Exception as e:
            messages.append(f"\n{symbol}\nসিগন্যাল: NO TRADE\nডেটা পাওয়া যায়নি: {e}")
    messages.append("\n⚠️ পরীক্ষামূলক ইন্ডিকেটর সংকেত; নিশ্চিত পূর্বাভাস নয়। আগে demo-তে যাচাই করুন। সাধারণ Forex ডেটা Quotex OTC-র দাম নয়।")
    send_telegram("\n".join(messages))

if __name__ == "__main__":
    main()
