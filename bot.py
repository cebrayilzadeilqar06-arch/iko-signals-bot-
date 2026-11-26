
import os
import re
import requests
from flask import Flask, request

app = Flask(__name__)

TOKEN = os.environ.get("BOT_TOKEN")
OTC_KEY = os.environ.get("OTCHARTS_API_KEY")
TG_API = f"https://api.telegram.org/bot{TOKEN}" if TOKEN else None
DATA_API = "https://otcharts.com/v1/candles"


def send_message(chat_id, text):
    if not TG_API:
        return
    try:
        requests.post(
            f"{TG_API}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=15
        ).raise_for_status()
    except requests.RequestException:
        app.logger.exception("Telegram xetasi")


def ema(values, period):
    result = values[0]
    alpha = 2 / (period + 1)
    for value in values[1:]:
        result = alpha * value + (1 - alpha) * result
    return result


def rsi(values, period=14):
    changes = [
        values[i] - values[i - 1]
        for i in range(1, len(values))
    ]
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
        return 100 if avg_gain else 50

    return 100 - 100 / (1 + avg_gain / avg_loss)


def get_signal(symbol):
    if not OTC_KEY:
        raise ValueError("OTCHARTS_API_KEY tapilmadi")

    response = requests.get(
        DATA_API,
        params={
            "venue": "otc",
            "symbol": symbol,
            "tf": 60,
            "limit": 100
        },
        headers={"Authorization": f"Bearer {OTC_KEY}"},
        timeout=20
    )

    if response.status_code != 200:
        raise ValueError(
            f"Pocket Option melumat xetasi: {response.status_code}"
        )

    data = response.json()
    candles = data.get("candles", [])

    # Son şam hələ formalaşır, analizə daxil edilmir.
    candles = candles[:-1]

    if len(candles) < 60:
        raise ValueError("Analiz ucun kifayet qeder sam yoxdur")

    if data.get("gaps", {}).get("missingBars", 0) > 0:
        raise ValueError("Qiymet melumatinda bosluq var")

    closes = [float(c["close"]) for c in candles]

    price = closes[-1]
    fast = ema(closes, 9)
    slow = ema(closes, 21)
    strength = rsi(closes)

    direction = "SIQNAL YOXDUR"

    if fast > slow and price > fast and 52 <= strength <= 68:
        direction = "YUXARI"
    elif fast < slow and price < fast and 32 <= strength <= 48:
        direction = "ASAGI"

    return direction, price, strength, fast, slow


@app.route("/", methods=["GET"])
def home():
    return "IKO Pocket Option OTC bot is running!"


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
        reply = (
            "IKO Pocket Option OTC siqnallari!\n\n"
            "/signal - EUR/USD OTC analizi\n"
            "/signal GBPUSD_otc - basqa aktiv\n\n"
            "Demo ucun istifade et. Qazanc zemaneti yoxdur."
        )

    elif command == "/signal":
        symbol = parts[1] if len(parts) > 1 else "EURUSD_otc"

        if not re.fullmatch(r"[A-Za-z0-9#]+_otc", symbol):
            reply = "Aktiv formatı yanlışdır. Nümunə: /signal EURUSD_otc"
        else:
            try:
                direction, price, strength, fast, slow = get_signal(symbol)

                reply = (
                    "IKO POCKET OPTION OTC\n"
                    f"Aktiv: {symbol}\n"
                    f"Istiqamet: {direction}\n"
                    "Muddet: 1 deqiqe\n"
                    f"Qiymet: {price}\n"
                    f"RSI: {strength:.1f}\n"
                    f"EMA 9: {fast}\n"
                    f"EMA 21: {slow}\n"
                    "Qazanc zemaneti yoxdur."
                )
            except (requests.RequestException, ValueError, KeyError) as e:
                app.logger.exception("OTC analiz xetasi")
                reply = f"OTC melumat alinmadi: {e}"

    else:
        reply = "Istifade et: /start ve ya /signal"

    send_message(chat_id, reply)
    return "OK"


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000))
    )
