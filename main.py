
import os
import json
import requests
import pandas as pd
from datetime import datetime
from pathlib import Path

# =============== CONFIGURATION ===============
API_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

SYMBOL = os.getenv("SYMBOL", "EUR/JPY")
MARKET_LABEL = os.getenv("MARKET_LABEL", "REAL MARKET")
TIMEFRAME = "1min"
CONFIRM_TIMEFRAME = "5min"
MIN_SCORE = 6

STATE_FILE = Path("alamin_state.json")
BOT_NAME = "ALAMIN SIGNAL"
# =============================================


def telegram_send(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    response = requests.post(
        url,
        json={"chat_id": CHAT_ID, "text": message},
        timeout=20
    )
    response.raise_for_status()

    if not response.json().get("ok"):
        raise RuntimeError("Telegram message could not be sent")


def get_candles(interval="1min", size=200):
    response = requests.get(
        "https://api.twelvedata.com/time_series",
        params={
            "symbol": SYMBOL,
            "interval": interval,
            "outputsize": size,
            "apikey": API_KEY,
            "timezone": "UTC",
            "format": "JSON"
        },
        timeout=20
    )
    response.raise_for_status()
    data = response.json()

    if "values" not in data:
        raise RuntimeError(
            f"Market data error: {data.get('message', data)}"
        )

    df = pd.DataFrame(data["values"])

    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["datetime"] = pd.to_datetime(
        df["datetime"], utc=True, errors="coerce"
    )

    df = (
        df.dropna(subset=["datetime", "open", "high", "low", "close"])
        .sort_values("datetime")
        .drop_duplicates("datetime")
        .reset_index(drop=True)
    )

    if len(df) < 80:
        raise RuntimeError("Not enough candles for analysis")

    # বাদ দাও বর্তমান অসম্পূর্ণ ক্যান্ডেল
    return df.iloc[:-1].copy().reset_index(drop=True)


def add_indicators(df):
    x = df.copy()

    # EMA 9, 21, 50
    for period in [9, 21, 50]:
        x[f"ema{period}"] = x["close"].ewm(
            span=period, adjust=False
        ).mean()

    # RSI 14
    delta = x["close"].diff()
    gain = delta.clip(lower=0).ewm(
        alpha=1/14, adjust=False
    ).mean()
    loss = (-delta.clip(upper=0)).ewm(
        alpha=1/14, adjust=False
    ).mean()

    rs = gain / loss.replace(0, float("nan"))
    x["rsi"] = (100 - 100 / (1 + rs)).fillna(50)

    # MACD
    ema12 = x["close"].ewm(span=12, adjust=False).mean()
    ema26 = x["close"].ewm(span=26, adjust=False).mean()
    x["macd"] = ema12 - ema26
    x["macd_signal"] = x["macd"].ewm(
        span=9, adjust=False
    ).mean()

    # ATR
    previous_close = x["close"].shift(1)
    tr = pd.concat([
        x["high"] - x["low"],
        (x["high"] - previous_close).abs(),
        (x["low"] - previous_close).abs()
    ], axis=1).max(axis=1)

    x["atr"] = tr.ewm(alpha=1/14, adjust=False).mean()

    # ADX approximation
    up = x["high"].diff()
    down = -x["low"].diff()

    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)

    atr_safe = x["atr"].replace(0, float("nan"))
    plus_di = 100 * plus_dm.ewm(
        alpha=1/14, adjust=False
    ).mean() / atr_safe
    minus_di = 100 * minus_dm.ewm(
        alpha=1/14, adjust=False
    ).mean() / atr_safe

    dx = 100 * (plus_di - minus_di).abs() / (
        plus_di + minus_di
    ).replace(0, float("nan"))

    x["adx"] = dx.ewm(
        alpha=1/14, adjust=False
    ).mean().fillna(0)

    # Bollinger Bands
    middle = x["close"].rolling(20).mean()
    deviation = x["close"].rolling(20).std()

    x["bb_mid"] = middle
    x["bb_upper"] = middle + 2 * deviation
    x["bb_lower"] = middle - 2 * deviation

    # Keltner Channel
    x["kc_mid"] = x["close"].ewm(
        span=20, adjust=False
    ).mean()
    x["kc_upper"] = x["kc_mid"] + 1.5 * x["atr"]
    x["kc_lower"] = x["kc_mid"] - 1.5 * x["atr"]

    return x


def find_swings(df, window=3):
    highs, lows = [], []

    for i in range(window, len(df) - window):
        if df["high"].iloc[i] >= df["high"].iloc[
            i-window:i+window+1
        ].max():
            highs.append((i, float(df["high"].iloc[i])))

        if df["low"].iloc[i] <= df["low"].iloc[
            i-window:i+window+1
        ].min():
            lows.append((i, float(df["low"].iloc[i])))

    return highs, lows


def analyze_market(raw, higher_raw):
    df = add_indicators(raw)
    higher = add_indicators(higher_raw)

    last = df.iloc[-1]
    prev = df.iloc[-2]

    price = float(last["close"])
    atr = max(float(last["atr"]), abs(price) * 0.00001)
    tolerance = atr * 0.25

    call_score = 0
    put_score = 0
    reasons = []

    def add(side, points, label):
        nonlocal call_score, put_score

        if side == "CALL":
            call_score += points
            reasons.append(f"CALL: {label}")
        elif side == "PUT":
            put_score += points
            reasons.append(f"PUT: {label}")

    # 1. Pivot Points
    prior = raw.iloc[-2]
    ph = float(prior["high"])
    pl = float(prior["low"])
    pc = float(prior["close"])
    pivot = (ph + pl + pc) / 3

    if price > pivot:
        add("CALL", 1, "Above Pivot")
    elif price < pivot:
        add("PUT", 1, "Below Pivot")

    # 2. Fibonacci Retracement
    swing_highs, swing_lows = find_swings(
        raw.tail(100).reset_index(drop=True)
    )

    swing_high = max(
        [v for _, v in swing_highs[-5:]],
        default=float(raw["high"].tail(50).max())
    )
    swing_low = min(
        [v for _, v in swing_lows[-5:]],
        default=float(raw["low"].tail(50).min())
    )

    span = max(swing_high - swing_low, tolerance)
    fib_levels = [
        swing_high - span * 0.382,
        swing_high - span * 0.500,
        swing_high - span * 0.618
    ]

    if any(abs(price - level) <= tolerance for level in fib_levels):
        if price >= float(last["ema21"]):
            add("CALL", 1, "Fibonacci zone")
        else:
            add("PUT", 1, "Fibonacci zone")

    # 3. Price Action / Candlestick
    body = abs(float(last["close"]) - float(last["open"]))
    lower_wick = min(
        float(last["close"]), float(last["open"])
    ) - float(last["low"])
    upper_wick = float(last["high"]) - max(
        float(last["close"]), float(last["open"])
    )

    bullish_engulf = (
        last["close"] > last["open"]
        and prev["close"] < prev["open"]
        and last["close"] >= prev["open"]
        and last["open"] <= prev["close"]
    )

    bearish_engulf = (
        last["close"] < last["open"]
        and prev["close"] > prev["open"]
        and last["close"] <= prev["open"]
        and last["open"] >= prev["close"]
    )

    if bullish_engulf or (
        lower_wick > max(body * 2, tolerance)
        and last["close"] > last["open"]
    ):
        add("CALL", 1, "Bullish price action")

    if bearish_engulf or (
        upper_wick > max(body * 2, tolerance)
        and last["close"] < last["open"]
    ):
        add("PUT", 1, "Bearish price action")

    # 4. Trend Following: EMA + ADX
    if (
        last["ema9"] > last["ema21"] > last["ema50"]
        and last["adx"] >= 18
    ):
        add("CALL", 2, "EMA/ADX uptrend")

    elif (
        last["ema9"] < last["ema21"] < last["ema50"]
        and last["adx"] >= 18
    ):
        add("PUT", 2, "EMA/ADX downtrend")

    # 5. RSI / MACD Divergence
    tail = df.tail(100).reset_index(drop=True)
    highs, lows = find_swings(tail)

    if len(lows) >= 2:
        i1, p1 = lows[-2]
        i2, p2 = lows[-1]

        if (
            p2 < p1
            and tail["rsi"].iloc[i2] > tail["rsi"].iloc[i1] + 3
        ):
            add("CALL", 1, "Bullish RSI divergence")

        if (
            p2 < p1
            and tail["macd"].iloc[i2] > tail["macd"].iloc[i1]
        ):
            add("CALL", 1, "Bullish MACD divergence")

    if len(highs) >= 2:
        i1, p1 = highs[-2]
        i2, p2 = highs[-1]

        if (
            p2 > p1
            and tail["rsi"].iloc[i2] < tail["rsi"].iloc[i1] - 3
        ):
            add("PUT", 1, "Bearish RSI divergence")

        if (
            p2 > p1
            and tail["macd"].iloc[i2] < tail["macd"].iloc[i1]
        ):
            add("PUT", 1, "Bearish MACD divergence")

    # 6. Breakout & Retest
    range_high = float(df["high"].iloc[-22:-2].max())
    range_low = float(df["low"].iloc[-22:-2].min())

    if (
        price > range_high
        and float(prev["low"]) <= range_high + tolerance
    ):
        add("CALL", 1, "Breakout/retest")

    elif (
        price < range_low
        and float(prev["high"]) >= range_low - tolerance
    ):
        add("PUT", 1, "Breakdown/retest")

    # 7. Volatility Squeeze
    squeeze = (
        float(prev["bb_upper"]) < float(prev["kc_upper"])
        and float(prev["bb_lower"]) > float(prev["kc_lower"])
    )

    if squeeze:
        if price > float(last["bb_mid"]):
            add("CALL", 1, "Volatility squeeze")
        elif price < float(last["bb_mid"]):
            add("PUT", 1, "Volatility squeeze")

    # 8. Multi-Timeframe Analysis
    h = higher.iloc[-1]

    if h["ema9"] > h["ema21"] and h["close"] > h["ema50"]:
        add("CALL", 1, "Higher timeframe bullish")
    elif h["ema9"] < h["ema21"] and h["close"] < h["ema50"]:
        add("PUT", 1, "Higher timeframe bearish")

    # 9. Fibonacci Confluence with Pivot levels
    pivot_levels = [
        pivot,
        2 * pivot - pl,
        2 * pivot - ph,
        pivot + (ph - pl),
        pivot - (ph - pl)
    ]

    confluence = any(
        abs(fib - level) <= tolerance
        for fib in fib_levels
        for level in pivot_levels
    )

    if confluence:
        if price > float(last["ema21"]):
            add("CALL", 1, "Fibonacci/Pivot confluence")
        elif price < float(last["ema21"]):
            add("PUT", 1, "Fibonacci/Pivot confluence")

    # 10. Market Structure / Liquidity Sweep
    recent_highs, recent_lows = find_swings(tail)

    if len(recent_highs) >= 2 and len(recent_lows) >= 2:
        recent_high = max(v for _, v in recent_highs[-3:])
        recent_low = min(v for _, v in recent_lows[-3:])

        if price > recent_high:
            add("CALL", 1, "Structure break up")
        elif price < recent_low:
            add("PUT", 1, "Structure break down")

        if float(last["low"]) < recent_low and price > recent_low:
            add("CALL", 1, "Sell-side liquidity sweep")

        if float(last["high"]) > recent_high and price < recent_high:
            add("PUT", 1, "Buy-side liquidity sweep")

    difference = call_score - put_score

    if call_score >= MIN_SCORE and difference >= 2:
        signal, status = "CALL", "STRONGER SETUP"
    elif put_score >= MIN_SCORE and difference <= -2:
        signal, status = "PUT", "STRONGER SETUP"
    else:
        # CALL/PUT only; low-confidence signal clearly labelled
        signal = "CALL" if difference >= 0 else "PUT"
        status = "LOW CONFIDENCE"

    return {
        "signal": signal,
        "status": status,
        "call_score": call_score,
        "put_score": put_score,
        "price": price,
        "time": last["datetime"],
        "reasons": reasons
    }


def load_pending():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def save_pending(items):
    STATE_FILE.write_text(
        json.dumps(items, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def check_results():
    """
    Approximate price-direction outcome, NOT broker settlement data.
    """
    pending = load_pending()
    if not pending:
        return

    try:
        df = get_candles(TIMEFRAME, 30)
    except Exception as exc:
        print("Result check failed:", exc)
        return

    latest = df.iloc[-1]
    latest_time = latest["datetime"]
    remaining = []

    for item in pending:
        entry_time = pd.to_datetime(item["entry_utc"], utc=True)

        if latest_time < entry_time + pd.Timedelta(minutes=1):
            remaining.append(item)
            continue

        entry_price = float(item["entry_price"])
        exit_price = float(latest["close"])

        if item["signal"] == "CALL":
            outcome = "PROFIT" if exit_price > entry_price else "LOSS"
        else:
            outcome = "PROFIT" if exit_price < entry_price else "LOSS"

        if outcome == "PROFIT":
            item["win"] += 1
        else:
            item["loss"] += 1

        result_message = (
            f"{SYMBOL} ( {MARKET_LABEL} )\n"
            f"Entry Time : {item['entry_local']}\n"
            f"RESULT : {outcome}\n"
            f"Win : {item['win']}\n"
            f"Loss : {item['loss']}\n"
            f"{BOT_NAME}"
        )

        try:
            telegram_send(result_message)
        except Exception as exc:
            print("Could not send result:", exc)
            remaining.append(item)

    save_pending(remaining)


def get_stats():
    try:
        data = json.loads(Path("alamin_stats.json").read_text(encoding="utf-8"))
        return int(data.get("win", 0)), int(data.get("loss", 0))
    except (OSError, ValueError, TypeError):
        return 0, 0


def main():
    if not API_KEY or not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError(
            "Set TWELVE_DATA_API_KEY, TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."
        )

    check_results()

    df = get_candles(TIMEFRAME)
    higher = get_candles(CONFIRM_TIMEFRAME)
    result = analyze_market(df, higher)

    # Entry is the next whole minute; local message time uses Bangladesh time.
    now_utc = datetime.now(timezone.utc)
    entry_utc = now_utc.replace(second=0, microsecond=0) + pd.Timedelta(minutes=1)
    entry_local = entry_utc.tz_convert("Asia/Dhaka").strftime("%H:%M")

    win, loss = get_stats()
    pending = load_pending()

    pending.append({
        "signal": result["signal"],
        "entry_utc": entry_utc.isoformat(),
        "entry_local": entry_local,
        "entry_price": result["price"],
        "win": win,
        "loss": loss
    })
    save_pending(pending)

    direction = "UP" if result["signal"] == "CALL" else "DOWN"

    signal_message = (
        f"{SYMBOL} ( {MARKET_LABEL} )\n"
        f"SIGNAL : {result['signal']}\n"
        f"ENTRY TIME : {entry_local}\n"
        f"TIMEFRAME : 1 MINUTE\n"
        f"DIRECTION : {direction}\n"
        f"{BOT_NAME}"
    )

    telegram_send(signal_message)
    print(signal_message)
    print(
        f"Analysis={result['status']} | "
        f"CALL={result['call_score']} | PUT={result['put_score']}"
    )


if __name__ == "__main__":
    main()
