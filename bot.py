import os
import time
import requests
from flask import Flask, request

app = Flask(__name__)

TOKEN = os.environ.get("BOT_TOKEN")
TG_API = f"https://api.telegram.org/bot{TOKEN}" if TOKEN else None
YAHOO_API = "https://query1.finance.yahoo.com/v8/finance/chart"

# Adi Forex cütləri. OTC aktivləri daxil deyil.
PAIRS = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "AUDUSD": "AUDUSD=X",
    "USDCAD": "USDCAD=X",
    "USDCHF": "USDCHF=X",
    "NZDUSD": "NZDUSD=X",
}


def send_message(chat_id, message):
    if not TG_API:
        app.logger.error("BOT_TOKEN is missing")
        return
    try:
        requests.post(
            f"{TG_API}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=15
        ).raise_for_status()
    except requests.RequestException:
        app.logger.exception("Telegram send error")


def ema(values, period):
    alpha = 2 / (period + 1)
    result = values[0]
    for value in values[1:]:
        result = alpha * value + (1 - alpha) * result
    return result


def rsi(values, period=14):
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(change, 0) for change in changes]
    losses = [max(-change, 0) for change in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(changes)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0 if avg_gain else 50.0
    return 100 - 100 / (1 + avg_gain / avg_loss)


def get_signal(pair, minutes):
    symbol = PAIRS[pair]
    interval = "1m" if minutes == 1 else "5m"

    response = requests.get(
        f"{YAHOO_API}/{symbol}",
        params={"range": "1d", "interval": interval},
        headers={"User-Agent": "Mozilla/5.0 (compatible; IKOSignals/1.0)"},
        timeout=20
    )
    response.raise_for_status()

    chart = response.json().get("chart", {})
    if chart.get("error"):
        raise ValueError("Məlumat mənbəyi bu cüt üçün cavab vermədi")

    results = chart.get("result") or []
    if not results:
        raise ValueError("Hazırda qiymət şamları yoxdur")

    result = results[0]
    timestamps = result.get("timestamp") or []
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []

    candles = [
        (int(ts), float(close))
        for ts, close in zip(timestamps, closes)
        if close is not None
    ]

    if len(candles) < 60:
        raise ValueError("Analiz üçün kifayət qədər şam yoxdur")

    # Son şam formalaşmaqda ola bilər; onu analizdən çıxarırıq.
    candles = candles[:-1]
    if len(candles) < 40:
        raise ValueError("Tamamlanmış şam sayı azdır")

    last_timestamp = candles[-1][0]
    age = int(time.time()) - last_timestamp
    max_age = 240 if minutes == 1 else 720
    if age > max_age:
        raise ValueError(
            f"Qiymət məlumatı köhnədir ({age // 60} dəq). "
            "Forex bazarı bağlı və ya məlumat mənbəyi gecikmiş ola bilər."
        )

    values = [item[1] for item in candles]
    price = values[-1]
    fast = ema(values[-40:], 9)
    slow = ema(values[-60:], 21)
    strength = rsi(values[-60:])

    # Şərtlər uyğun gəlmirsə, məcburi siqnal vermir.
    direction = "SIQNAL YOXDUR"
    if fast > slow and price > fast and 52 <= strength <= 68:
        direction = "YUXARI (CALL)"
    elif fast < slow and price < fast and 32 <= strength <= 48:
        direction = "AŞAĞI (PUT)"

    return direction, price, strength, fast, slow, age


def help_text():
    return (
        "IKO Forex Siqnalları — OTC yoxdur\n\n"
        "/signal - EUR/USD, 1 dəqiqə\n"
        "/signal GBPUSD - GBP/USD, 1 dəqiqə\n"
        "/signal EURUSD 5 - EUR/USD, 5 dəqiqə\n"
        "/pairs - valyuta cütlərinin siyahısı\n"
        "/help - kömək\n\n"
        "Mənbə: Yahoo Finance-in qeyri-rəsmi məlumat interfeysi. "
        "Qiymətlər Pocket Option ilə fərqlənə və gecikə bilər. "
        "Əvvəl demo hesabda yoxla. Qazanc zəmanəti yoxdur."
    )


@app.route("/", methods=["GET"])
def home():
    return "IKO Forex Signals bot is running (non-OTC)."


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}
    message = data.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    raw = (message.get("text") or "").strip()

    if not chat_id:
        return "OK"

    parts = raw.split()
    command = parts[0].lower().split("@")[0] if parts else ""

    if command in ("/start", "/help"):
        reply = help_text()

    elif command == "/pairs":
        reply = (
            "Adi Forex cütləri (OTC deyil):\n"
            + ", ".join(PAIRS.keys())
            + "\n\nNümunə: /signal EURUSD 1"
        )

    elif command == "/signal":
        pair = parts[1].upper().replace("/", "") if len(parts) > 1 else "EURUSD"
        timeframe = 1

        if len(parts) > 2:
            if parts[2] not in ("1", "5"):
                reply = "Müddət 1 və ya 5 dəqiqə olmalıdır. Nümunə: /signal EURUSD 5"
                send_message(chat_id, reply)
                return "OK"
            timeframe = int(parts[2])

        if pair not in PAIRS:
            reply = "Bu cüt dəstəklənmir. /pairs yazaraq siyahıya bax."
        else:
            try:
                direction, price, strength, fast, slow, age = get_signal(pair, timeframe)
                digits = 3 if "JPY" in pair else 5
                reply = (
                    "IKO FOREX DEMO SIQNALI (OTC DEYİL)\n"
                    f"Cüt: {pair}\n"
                    f"İstiqamət: {direction}\n"
                    f"Analiz müddəti: {timeframe} dəqiqə\n"
                    f"Son qiymət: {price:.{digits}f}\n"
                    f"RSI 14: {strength:.1f}\n"
                    f"EMA 9: {fast:.{digits}f}\n"
                    f"EMA 21: {slow:.{digits}f}\n"
                    f"Məlumat yaşı: təxminən {age} saniyə\n"
                    "Mənbə: Yahoo Finance; Pocket Option qiyməti ilə fərqlənə bilər.\n"
                    "Qazanc zəmanəti yoxdur. Demo hesabda yoxla."
                )
            except (requests.RequestException, ValueError, KeyError, TypeError) as error:
                app.logger.exception("Forex data error")
                reply = f"Forex məlumatı alınmadı: {str(error)[:250]}"

    else:
        reply = "Əmr tanınmadı. /start, /signal və ya /pairs yaz."

    send_message(chat_id, reply)
    return "OK"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
