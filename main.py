import time
import schedule
import requests
import logging
from telegram import Bot
from pybit.unified_trading import HTTP
from functools import lru_cache

# === Логирование ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# === Конфигурация ===
TELEGRAM_TOKEN = "8035943979:AAHnEJsv1fQwSfMocXhXAeuNH_dck7eZkdA"
CHAT_ID = "662228268"
OPENROUTER_API_KEY = "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"

# Bybit API
BYBIT_API_KEY = "02lQBpPCobvcDq6ZNO"
BYBIT_API_SECRET = "izcRJchKBshql5hVFPgXn0hLBTAK7LBiJnVj"

# CryptoPanic
CRYPTOPANIC_API_KEY = "6ecc17426b376c95faac531793099ccd1ccebacd"

# === Инициализация клиентов ===
bot = Bot(token=TELEGRAM_TOKEN)
bybit = HTTP(api_key=BYBIT_API_KEY, api_secret=BYBIT_API_SECRET)

# ------------------------------------------------------------
# Получение свечей с кэшированием
# ------------------------------------------------------------
@lru_cache(maxsize=128)
def get_candles(symbol: str, interval: str, limit=50):
    try:
        response = bybit.get_kline(
            category="linear",
            symbol=symbol,
            interval=interval,
            limit=limit
        )
        candles = [
            {
                "time": int(k[0]),
                "open": k[1],
                "high": k[2],
                "low": k[3],
                "close": k[4],
                "volume": k[5],
            }
            for k in response.get("result", {}).get("list", [])
        ]
        return candles
    except Exception as e:
        logging.error(f"Ошибка при получении свечей: {e}")
        return []

# ------------------------------------------------------------
# Новости с CryptoPanic
# ------------------------------------------------------------
@lru_cache(maxsize=1)
def get_news():
    try:
        url = f"https://cryptopanic.com/api/v1/posts/?auth_token={CRYPTOPANIC_API_KEY}&currencies=BTC,SOL,XRP,ETH"
        r = requests.get(url)
        data = r.json()
        news_list = []
        for item in data.get("results", [])[:10]:
            news_list.append(f"{item['title']} ({item['published_at']})")
        return "\n".join(news_list)
    except Exception as e:
        logging.error(f"Ошибка при получении новостей: {e}")
        return "Новости недоступны."

# ------------------------------------------------------------
# Сбор данных с рынка
# ------------------------------------------------------------
def collect_market_data():
    pairs = ["BTCUSDT", "SOLUSDT", "XRPUSDT", "ETHUSDT"]
    intervals = {
        "1h": "60",
        "4h": "240",
        "1d": "D"
    }

    all_data = {}
    for pair in pairs:
        all_data[pair] = {}
        for tf, interval in intervals.items():
            all_data[pair][tf] = get_candles(pair, interval, limit=50)
    return all_data

# ------------------------------------------------------------
# Анализ с помощью OpenRouter (OpenChat-3.5)
# ------------------------------------------------------------
def get_gpt_analysis(market_data, news):
    # Берём последние цены закрытия по 1h таймфрейму
    latest_prices = {}
    for coin in market_data:
        if market_data[coin]["1h"]:
            last_candle = market_data[coin]["1h"][-1]
            latest_prices[coin] = last_candle["close"]
        else:
            latest_prices[coin] = "нет данных"

    prices_str = "\n".join([f"{coin}: {price} USD" for coin, price in latest_prices.items()])

    prompt = f"""
Ты профессиональный крипто-трейдер.
Вот последние новости и рыночные данные.

Новости:
{news}

Актуальные цены (последнее закрытие 1h):
{prices_str}

Данные рынка (исторические свечи):
{market_data}

Проанализируй новости и технические данные для BTC, SOL, XRP и ETH.
Дай краткий прогноз движения цены по таймфреймам 1h, 4h и 1d.
Укажи ключевые уровни и краткий вывод по каждой монете. Ответы давай на русском языке.
Используй последние цены закрытия (1h) как текущие цены. Не используй устаревшие данные как актуальные.
"""

    data = {
        "model": "meta-llama/llama-3-70b-instruct",
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
        "max_tokens": 1000
    }

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://yourproject.com",
            "X-Title": "Crypto AI Bot"
        },
        json=data
    )

    if response.status_code != 200:
        raise Exception(f"OpenRouter API error: {response.status_code} - {response.text}")

    return response.json()["choices"][0]["message"]["content"].strip()

# ------------------------------------------------------------
# Отправка длинного текста в Telegram
# ------------------------------------------------------------
def send_long_message(bot, chat_id, text):
    for i in range(0, len(text), 4096):
        bot.send_message(chat_id=chat_id, text=text[i:i+4096])

# ------------------------------------------------------------
# Задача для schedule
# ------------------------------------------------------------
def job():
    try:
        logging.info("Запуск задачи анализа рынка...")
        news = get_news()
        market_data = collect_market_data()
        analysis = get_gpt_analysis(market_data, news)
        send_long_message(bot, CHAT_ID, analysis)
        logging.info("Успешно отправлен прогноз.")
    except Exception as e:
        error_message = f"Ошибка: {e}"
        logging.error(error_message)
        bot.send_message(chat_id=CHAT_ID, text=error_message)

# Первый запуск при старте
job()

# Запуск задачи каждые 4 часа
schedule.every(4).hours.do(job)

while True:
    schedule.run_pending()
    time.sleep(10)
