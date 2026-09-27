"""Бот заявок: пересылает заявки с сайта в Telegram владельцу.

Как работает:
  1. посетитель отправляет форму на сайте;
  2. app.py кладёт заявку в очередь data/orders.db;
  3. этот бот забирает новые заявки и шлёт их в чат ORDERS_ADMIN_CHAT_ID;
  4. у сообщения есть кнопки «Прочитано» и «Перезвонить» — статус пишется
     в базу, поэтому переживает перезапуск бота.

Сайт при этом не зависит от Telegram: если сеть лежит, заявка просто ждёт
в очереди и уходит при следующей попытке.

Запуск (из корня проекта):
    python -m orders.bot
    python orders\\bot.py       # тоже работает
"""

import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# Позволяет запускать файл напрямую: тогда в sys.path нет корня проекта
# и не нашлись бы ни config, ни пакет orders.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import telebot  # noqa: E402  — импорт после правки sys.path, так и задумано
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup  # noqa: E402

from config import (  # noqa: E402
    ORDERS_ADMIN_CHAT_ID,
    REQUESTS_BOT_TOKEN,
    SITE_URL,
    check_requests_config,
)
from orders.store import (  # noqa: E402
    FINAL_STATUSES,
    STATUS_CALLED,
    STATUS_NEW,
    STATUS_READ,
    STATUS_SENT,
    format_order,
    get_order,
    mark_failed,
    mark_sent,
    pending,
    queue_size,
    recent,
    set_status,
)

# Как часто проверять очередь. Заявка должна доходить за секунды, а не за минуты.
POLL_SECONDS = 2

# Сколько заявок отправляем за один проход: не даём боту зависнуть на длинной
# очереди и блокировать обработку кнопок.
BATCH_SIZE = 20

# Префикс callback_data. По нему отличаем наши кнопки от чужих.
CALLBACK_PREFIX = "order:"

# Отметки, которые добавляются к тексту заявки при нажатии кнопки.
# Заодно служат подписью статуса в /orders.
STATUS_LINES = {
    STATUS_NEW: "⏳ ждёт отправки",
    STATUS_SENT: "📨 отправлено, ждёт ответа",
    STATUS_READ: "✅ Прочитано",
    STATUS_CALLED: "📞 Перезвонил",
}

bot = telebot.TeleBot(REQUESTS_BOT_TOKEN, parse_mode="HTML")

# Заявки шлёт поток очереди, кнопки обрабатывает поток polling.
# telebot не потокобезопасен на запись — выстраиваем отправку в очередь.
_send_lock = threading.Lock()


def log(message):
    """Печать в консоль с меткой времени."""
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}", flush=True)


def keyboard(order_id):
    """Кнопки под заявкой. После «Прочитано»/«Перезвонить» их убираем."""
    if get_order(order_id)["status"] in FINAL_STATUSES:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            "✅ Прочитано", callback_data=f"{CALLBACK_PREFIX}read:{order_id}"
        ),
        InlineKeyboardButton(
            "📞 Перезвонить", callback_data=f"{CALLBACK_PREFIX}call:{order_id}"
        ),
    ]])


def send_order(order):
    """Отправляет одну заявку. Возвращает True, если ушла."""
    with _send_lock:
        message = bot.send_message(
            ORDERS_ADMIN_CHAT_ID,
            format_order(order),
            reply_markup=keyboard(order["id"]),
        )
    mark_sent(order["id"], message.message_id)
    log(f"Заявка #{order['id']} отправлена ({order['name']}, {order['phone']})")
    return True


def flush_queue():
    """Один проход по очереди: отправляет всё, что готово.

    Ошибка по одной заявке не должна останавливать остальные, поэтому
    каждую обрабатываем в своём try/except.
    """
    sent = 0
    for order in pending(limit=BATCH_SIZE):
        try:
            send_order(order)
            sent += 1
        except Exception as error:
            mark_failed(order["id"])
            log(f"Заявка #{order['id']} не отправлена: {error!r}")
    return sent


def queue_watcher():
    """Поток: раз в POLL_SECONDS проверяет очередь и отправляет новые заявки.

    Опрос вместо сигнала от сайта: Flask и бот — разные процессы, и связать
    их событием без очереди в базе нельзя. Две секунды — это и есть «сразу».
    """
    log("Слежу за очередью заявок")
    while True:
        try:
            flush_queue()
        except Exception as error:
            log(f"Ошибка очереди: {error!r}")
        time.sleep(POLL_SECONDS)


def is_admin(chat_id):
    """Заявки видит только владелец, который указал свой chat_id."""
    return chat_id == ORDERS_ADMIN_CHAT_ID


@bot.message_handler(commands=["start", "help"])
def start(message):
    """Что умеет бот и куда оставлять заявку."""
    if not is_admin(message.chat.id):
        return
    bot.send_message(
        message.chat.id,
        "Бот заявок. Сюда приходят заявки с сайта — с временем, именем, "
        "телефоном, прибором, адресом и описанием проблемы.\n"
        "У каждой заявки есть кнопки «Прочитано» и «Перезвонить».\n"
        "Команда /orders покажет последние заявки и очередь.",
    )


@bot.message_handler(commands=["orders"])
def orders(message):
    """Сводка: сколько ждут отправки и последние заявки."""
    if not is_admin(message.chat.id):
        return
    lines = [f"В очереди на отправку: {queue_size()}"]
    latest = recent(limit=5)
    if not latest:
        lines.append("Заявок пока нет.")
    for order in latest:
        lines.append(
            f"#{order['id']} {order['name']} · {order['phone']} · "
            f"{order['device']} · {STATUS_LINES.get(order['status'], order['status'])}"
        )
    bot.send_message(message.chat.id, "\n".join(lines))


@bot.message_handler(func=lambda message: True)
def reply_to_visitors(message):
    """Любое другое сообщение: подсказываем, где оставить заявку.

    Раньше бот сам собирал заявки из переписки, но их неудобно было читать
    и они не попадали в ту же очередь. Теперь единый путь — форма на сайте.
    """
    bot.send_message(
        message.chat.id,
        f"Этот бот передаёт заявки владельцу сервиса.\n"
        f"Оставить заявку можно на сайте: {SITE_URL}",
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith(CALLBACK_PREFIX))
def on_status(call):
    """Обработка кнопок «Прочитано» / «Перезвонить»."""
    if not is_admin(call.message.chat.id):
        return

    _, action, order_id = call.data.split(":", 2)
    status = STATUS_READ if action == "read" else STATUS_CALLED

    order = set_status(int(order_id), status)
    if order is None:
        bot.answer_callback_query(call.id, "Заявка не найдена")
        return

    bot.answer_callback_query(
        call.id, STATUS_LINES[status].split(" ", 1)[-1].capitalize()
    )
    # Перерисовываем сообщение с новой отметкой и убираем кнопки —
    # иначе можно было бы бесконечно переключать статус туда-сюда.
    with _send_lock:
        bot.edit_message_text(
            format_order(order, status_line=STATUS_LINES[status]),
            call.message.chat.id,
            call.message.message_id,
            reply_markup=None,
        )
    log(f"Заявка #{order_id}: {status}")


if __name__ == "__main__":
    check_requests_config()

    log(f"Заявки будут уходить в чат {ORDERS_ADMIN_CHAT_ID}")
    log(f"Опрос очереди раз в {POLL_SECONDS} с")
    threading.Thread(target=queue_watcher, daemon=True).start()

    log("Запуск polling")
    try:
        bot.polling(none_stop=True, skip_pending=True)
    except telebot.apihelper.TelegramConflictError:
        sys.exit(
            "Этот бот уже запущен в другом процессе. Telegram не даёт двум "
            "ботам с одним токеном читать сообщения одновременно."
        )
    except KeyboardInterrupt:
        log("Остановлен")
