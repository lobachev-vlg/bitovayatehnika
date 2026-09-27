"""Бот, принимающий заявки в Telegram.

Человек пишет боту заявку текстом, бот складывает её в data/telegram_orders.txt.

Внимание: это отдельный канал от формы на сайте. Заявка с сайта попадает в
data/requests.csv и сюда не попадает — файлы разные, общей таблицы заявок нет.

Запуск (из корня проекта):
    python -m orders.bot
    python orders\\bot.py       # тоже работает
"""

import sys
from datetime import datetime
from pathlib import Path

# Позволяет запускать файл напрямую: тогда в sys.path нет корня проекта
# и не нашлись бы ни config, ни paths.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import telebot  # noqa: E402  — импорт после правки sys.path, так и задумано

from config import REQUESTS_BOT_TOKEN, check_requests_config  # noqa: E402
from paths import data_file  # noqa: E402

bot = telebot.TeleBot(REQUESTS_BOT_TOKEN)
ORDERS_FILE = data_file("telegram_orders.txt")


def log(message):
    """Печать в консоль с меткой времени."""
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}", flush=True)


def sender_name(user):
    """Имя отправителя: username, а если его нет — имя и id.

    username у Telegram бывает None, писать в файл "None" нельзя.
    """
    if not user:
        return "unknown"
    return user.username or f"{user.first_name or ''} (id={user.id})".strip()


@bot.message_handler(commands=["start"])
def start(message):
    """Подсказка по формату заявки."""
    bot.send_message(
        message.chat.id,
        "Отправь заявку в формате: Имя, Телефон, Техника, Проблема",
    )


@bot.message_handler(func=lambda message: True)
def register_order(message):
    """Любое текстовое сообщение считаем заявкой и дописываем в файл.

    Стоимость входа у /start выше, поэтому команда сюда не попадает.
    """
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} | {sender_name(message.from_user)} | {message.text}\n"
    try:
        with open(ORDERS_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError as error:
        log(f"Не удалось сохранить заявку: {error!r}")
        bot.send_message(message.chat.id, "Не удалось сохранить заявку. Попробуй ещё раз.")
        return

    log(f"Заявка от {sender_name(message.from_user)}")
    bot.send_message(message.chat.id, "Заявка зарегистрирована.")


if __name__ == "__main__":
    check_requests_config()
    log(f"Заявки будут складываться в {ORDERS_FILE}")
    try:
        bot.polling()
    except KeyboardInterrupt:
        log("Остановлен")
