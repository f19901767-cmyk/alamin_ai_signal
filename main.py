
import os
import requests

API_KEY = os.environ["TWELVE_DATA_API_KEY"]
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

def ema(values, period):
    alpha = 2 / (period + 1)
    result = values[0]
    for v in values[1:]:
        result = alpha * v + (1 - alpha) * result
    return result

def rsi(values, period=14):
    changes = [values[i] - values[i-1] for i in range(1, len(values))]
    gains = [max(x, 0) for x in changes]
    losses = [max(-x, 0) for x in changes]
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100 if avg_gain else 50
    return 100 - (100 / (1 + avg_gain / avg_loss))

def get_signal():
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": "EUR/JPY",
        "interval": "1min",
        "outputsize": 100,
        "apikey": API_KEY
    }

    response = requests.get(url, params=params, timeout=20)
    response.raise_for_status()
    data = response.json()

    if "values" not in data:
        raise RuntimeError(data.get("message", "Market data unavailable"))

    candles = list(reversed(data["values"]))

    # সর্বশেষ চলমান ক্যান্ডেল বাদ দিয়ে বন্ধ ক্যান্ডেল ব্যবহার
    candles = candles[:-1]
    if len(candles) < 60:
        return "NO TRADE", "পর্যাপ্ত ক্যান্ডেল নেই"

    closes = [float(c["close"]) for c in candles]
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]

    close = closes[-1]
    previous_close = closes[-2]

    ema9 = ema(closes[-40:], 9)
    ema21 = ema(closes[-60:], 21)

    current_rsi = rsi(closes, 14)

    # MACD 12,26,9
    macd_line = ema(closes[-60:], 12) - ema(closes[-60:], 26)
    macd_history = []
    for i in range(35, len(closes) + 1):
        segment = closes[:i]
        macd_history.append(
            ema(segment[-35:], 12) - ema(segment[-35:], 26)
        )
    signal_line = ema(macd_history, 9)

    # Bollinger Bands 20,2
    window = closes[-20:]
    mean = sum(window) / 20
    variance = sum((x - mean) ** 2 for x in window) / 20
    std = variance ** 0.5
    upper = mean + 2 * std
    lower = mean - 2 * std

    # ADX-এর সরল 14-period হিসাব
    plus_dm, minus_dm, tr_values = [], [], []
    for i in range(-14, 0):
        up = highs[i] - highs[i-1]
        down = lows[i-1] - lows[i]
        plus_dm.append(max(up, 0) if up > down else 0)
        minus_dm.append(max(down, 0) if down > up else 0)
        tr_values.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        ))

    atr = sum(tr_values) / 14
    if atr == 0:
        return "NO TRADE", "বাজারের অস্থিরতা নেই"

    plus_di = 100 * sum(plus_dm) / (14 * atr)
    minus_di = 100 * sum(minus_dm) / (14 * atr)
    adx_proxy = 100 * abs(plus_di - minus_di) / max(plus_di + minus_di, 0.001)

    # সাম্প্রতিক Support/Resistance
    support = min(lows[-20:])
    resistance = max(highs[-20:])
    candle_up = close > previous_close
    candle_down = close < previous_close

    call_score = 0
    put_score = 0

    if ema9 > ema21:
        call_score += 2
    elif ema9 < ema21:
        put_score += 2

    if current_rsi > 52:
        call_score += 1
    elif current_rsi < 48:
        put_score += 1

    if macd_line > signal_line:
        call_score += 1
    elif macd_line < signal_line:
        put_score += 1

    if close > mean:
        call_score += 1
    elif close < mean:
        put_score += 1

    if plus_di > minus_di:
        call_score += 1
    elif minus_di > plus_di:
        put_score += 1

    if candle_up:
        call_score += 1
    elif candle_down:
        put_score += 1

    # গুরুত্বপূর্ণ লেভেলের খুব কাছে থাকলে এন্ট্রি এড়িয়ে চলা
    near_resistance = (resistance - close) <= atr * 0.25
    near_support = (close - support) <= atr * 0.25

    if adx_proxy < 15:
        return "NO TRADE", "ট্রেন্ড দুর্বল"

    if call_score >= 6 and call_score - put_score >= 3:
        if near_resistance or current_rsi >= 75 or close >= upper:
            return "NO TRADE", "Resistance/overbought ঝুঁকি"
        return "CALL", f"Score {call_score}/7 | RSI {current_rsi:.1f}"

    if put_score >= 6 and put_score - call_score >= 3:
        if near_support or current_rsi <= 25 or close <= lower:
            return "NO TRADE", "Support/oversold ঝুঁকি"
        return "PUT", f"Score {put_score}/7 | RSI {current_rsi:.1f}"

    return "NO TRADE", f"CALL {call_score}/7 | PUT {put_score}/7"

def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    response = requests.post(
        url,
        data={"chat_id": CHAT_ID, "text": message},
        timeout=15
    )
    response.raise_for_status()

if __name__ == "__main__":
    signal, reason = get_signal()
    message = (
        "EUR/JPY | REAL FOREX\n"
        f"Signal: {signal}\n"
        "Timeframe: 1 Minute\n"
        f"Reason: {reason}\n"
        "Multi-indicator analysis — not guaranteed."
    )
    send_telegram(message)
