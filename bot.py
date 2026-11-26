
import os
import requests
from flask import Flask, request

app = Flask(__name__)

TOKEN = os.environ.get("BOT_TOKEN")
API = f"https://api.telegram.org/bot{TOKEN}" if TOKEN else None


def send_message(chat_id, text):
    if not API:
        app.logger.error("BOT_TOKEN yoxdur")
        return

    try:
        requests.post(
            f"{API}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10
        ).raise_for_status()
    except requests.RequestException:
        app.logger.exception("Telegram xetasi")


def ema(values, period):
    alpha = 2 / (period + 1)
    result = values[0]

    for value in values[1:]:
        result = alpha * value + (1 - alpha) * result

    return result


def rsi(closes, period=14):
    changes = [
        closes[i] - closes[i - 1]
        for i in range(1, len(closes))
    ]

    if len(changes) < period:
        raise ValueError("RSI ucun melumat azdir")

    gains = [max(x, 0) for x in changes]
    losses = [max(-x, 0) for x in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(changes)):
        avg_gain = (
            avg_gain * (period - 1) + gains[i]
        ) / period
        avg_loss = (
            avg_loss * (period - 1) + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def get_signal():
    response = requests.get(
        "https://api.binance.com/api/v3/klines",
        params={
            "symbol": "BTCUSDT",
            "interval": "1m",
            "limit": 100
        },
        timeout=10
    )
    response.raise_for_status()

    candles = response.json()
    closes = [float(c[4]) for c in candles[:-1]]

    if len(closes) < 60:
        raise ValueError("Melumat azdir")

    price = closes[-1]
    fast = ema(closes[-30:], 9)
    slow = ema(closes[-60:], 21)
    strength = rsi(closes)

    direction = None

    if fast > slow and price > fast and 52 <= strength <= 68:
        direction = "YUXARI"
    elif fast < slow and price < fast and 32 <= strength <= 48:
        direction = "ASAGI"

    return direction, strength, price, fast, slow


@app.route("/", methods=["GET"])
def home():
    return "IKO Signals is running!"


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}
    message = data.get("message") or {}

    chat_id = (message.get("chat") or {}).get("id")
    raw_text = message.get("text") or ""

    # Əmri boşluq və bot istifadəçi adı ilə birlikdə tanı
    parts = raw_text.strip().lower().split()
    command = parts[0].split("@", 1)[0] if parts else ""

    if not chat_id:
        return "OK"

    if command in ("/start", "/help"):
        reply = (
            "Salam! IKO Siqnallar botuna xos gelmisen!\n\n"
            "/signal - 1 deqiqelik demo analiz\n"
            "/help - komek\n\n"
            "Bu sınaq sistemidir. Qazanc zəmanəti yoxdur. "
            "Binance qiymətləri Pocket Option OTC ilə fərqlənə bilər."
        )

    elif command == "/signal":
        try:
            direction, strength, price, fast, slow = get_signal()

            if direction:
                reply = (
                    f"IKO DEMO SIQNALI\n"
                    f"BTC/USDT: {direction}\n"
                    f"Müddət: 1 dəqiqə\n"
                    f"Qiymət: {price:.2f}\n"
                    f"RSI: {strength:.1f}\n"
                    f"EMA 9: {fast:.2f}\n"
                    f"EMA 21: {slow:.2f}\n"
                    "Qazanc zəmanəti yoxdur."
                )
            else:
                reply = (
                    f"SIQNAL YOXDUR\n"
                    f"BTC/USDT: {price:.2f}\n"
                    f"RSI: {strength:.1f}\n"
                    "Şərtlər uyğun deyil. Gözlə."
                )

        except (requests.RequestException, ValueError, KeyError, IndexError):
            app.logger.exception("Analiz xetasi")
            reply = "Məlumat alınmadı. Bir az sonra yenidən yoxla."

    else:
        reply = (
            f"Əmr tanınmadı.\n"
            f"Alınan mətn: {raw_text!r}\n"
            "İstifadə et: /start və ya /signal"
        )

    send_message(chat_id, reply)
    return "OK"


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000))
    )
