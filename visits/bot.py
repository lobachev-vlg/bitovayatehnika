"""Бот статистики посещений: сам отправляет отчёты по расписанию.

Что делает:
  * каждый час  — список людей, зашедших в прошедший час;
  * каждый день — список людей за прошедший день;
  * каждую неделю (пн в 00:00) — число людей за прошедшую неделю.

Правило из задания: если людей больше 100, вместо списка уходит одно число.
Неделя — всегда только число.

Запуск (из корня проекта):
    python -m visits.bot
    python visits\\bot.py       # тоже работает
"""

import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

# Позволяет запускать файл напрямую: тогда в sys.path нет корня проекта
# и не нашлись бы ни config, ни пакет visits.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import telebot  # noqa: E402  — импорт после правки sys.path, так и задумано

from config import VISITS_ADMIN_CHAT_ID, VISITS_BOT_TOKEN, check_visits_config  # noqa: E402
from visits.store import (  # noqa: E402
    LIST_LIMIT,
    LIST_PERIODS,
    PERIODS,
    current_window,
    period_stats,
    previous_window,
    short_user_agent,
)

# Telegram не принимает сообщение длиннее 4096 символов. Запас 96 символов
# оставляем на случай, если счётчик в подписи вырастет.
MESSAGE_LIMIT = 4000

# Отчёт всегда про закрытый период, поэтому ждать границы достаточно
# один раз — дальше цикл считает следующую границу заново.
SLEEP_SLICE = 30

bot = telebot.TeleBot(VISITS_BOT_TOKEN)

# Отправкой занимаются три потока планировщика и обработчики команд.
# telebot не потокобезопасен на записи, поэтому выстраиваем их в очередь.
_send_lock = threading.Lock()


def log(message):
    """Печать в консоль с меткой времени — за ней видно, что бот жив."""
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}", flush=True)


def period_label(kind, start, end):
    """Заголовок отчёта с названием периода."""
    if kind == "hour":
        return f"Час {start:%H:%M}–{end:%H:%M}, {start:%d.%m.%Y}"
    if kind == "day":
        return f"День {start:%d.%m.%Y}"
    return f"Неделя {start:%d.%m}–{(end - timedelta(days=1)):%d.%m.%Y}"


def build_report(stats):
    """Собирает текст отчёта по данным period_stats.

    Час и день — список людей, пока их не больше LIST_LIMIT.
    Больше — только число. Неделя — только число.
    """
    kind = stats["kind"]
    unique = stats["unique"]
    head = f"{period_label(kind, stats['start'], stats['end'])}\nЛюдей: {unique}"

    if kind not in LIST_PERIODS or unique > LIST_LIMIT:
        return head

    lines = [head, f"Просмотров: {stats['views']}"]
    if stats["visitors"]:
        lines.append("")
        for visitor in stats["visitors"]:
            lines.append(
                f"  {datetime.fromtimestamp(visitor['first_ts']):%H:%M}  "
                f"{visitor['ip']}  x{visitor['hits']}  "
                f"{short_user_agent(visitor['user_agent'])}"
            )
    return "\n".join(lines)


def split_message(text, limit=MESSAGE_LIMIT):
    """Режет текст на куски по границам строк, чтобы влезать в лимит Telegram.

    Резать по границам строк важно: обрезанная посередине строка списка
    людей читалась бы как обрывок данных. Но если отдельная строка сама
    длиннее лимита, её приходится рвать — иначе Telegram отвергнет всё
    сообщение целиком.
    """
    chunks, current = [], ""

    def flush():
        nonlocal current
        if current:
            chunks.append(current)
            current = ""

    for line in text.splitlines():
        while len(line) > limit:
            flush()
            chunks.append(line[:limit])
            line = line[limit:]
        if current and len(current) + len(line) + 1 > limit:
            flush()
        current = f"{current}\n{line}" if current else line
    flush()

    # Пустой текст отправлять нельзя — Telegram отвергнет такое сообщение.
    return chunks or ["(пусто)"]


def send_report(chat_id, text):
    """Отправляет отчёт, при нехватке места — несколькими сообщениями."""
    chunks = split_message(text)
    with _send_lock:
        for chunk in chunks:
            bot.send_message(chat_id, chunk)
    log(f"Отправлено сообщений: {len(chunks)}, символов: {len(text)}")


def report_now(kind):
    """Считает закрытый период и отправляет отчёт админу."""
    send_report(VISITS_ADMIN_CHAT_ID, build_report(period_stats(kind)))


def scheduler(kind):
    """Отдельный поток на один период: ждёт границу и шлёт отчёт.

    Отчёт всегда по закрытому периоду. Ждём границу открытого периода
    (current_window), а не конца предыдущего: конец предыдущего уже в
    прошлом, и цикл схлопнулся бы в бесконечную отправку отчётов.
    """
    log(f"Планировщик '{kind}' запущен")
    while True:
        _, boundary = current_window(kind)
        target = boundary.timestamp()
        while True:
            delay = target - time.time()
            if delay <= 0:
                break
            # Спим кусками, а не до упоя: так системные часы не уводят
            # нас мимо границы, если сработает перевод времени.
            time.sleep(min(delay, SLEEP_SLICE))
        try:
            report_now(kind)
        except Exception as error:
            # Ошибка сети или Telegram не должна убивать поток: следующая
            # граница — через час, а не через минуту. Повторяем на ней.
            log(f"Ошибка отчёта '{kind}': {error!r}")


def is_admin(chat_id):
    """Отчёты видит только владелец, который указал свой chat_id."""
    return chat_id == VISITS_ADMIN_CHAT_ID


@bot.message_handler(commands=["start", "help"])
def start(message):
    """Описание бота и список команд."""
    if not is_admin(message.chat.id):
        return
    bot.send_message(
        message.chat.id,
        "Бот статистики посещений.\n"
        "Отчёты присылаются автоматически: за час, за день, за неделю.\n"
        "Час и день: список людей, если их больше 100 — только число.\n"
        "Неделя: только число людей.\n"
        "Команды: /stats hour, /stats day, /stats week",
    )


@bot.message_handler(commands=["stats"])
def stats(message):
    """Отчёт по запросу: /stats [hour|day|week], без аргумента — за день."""
    if not is_admin(message.chat.id):
        return
    parts = message.text.split()
    kind = parts[1].lower() if len(parts) > 1 else "day"
    if kind not in PERIODS:
        bot.send_message(
            message.chat.id,
            f"Неизвестный период: {kind}. Допустимо: {', '.join(PERIODS)}.",
        )
        return
    report_now(kind)


if __name__ == "__main__":
    check_visits_config()

    log(f"Отчёты будут уходить в чат {VISITS_ADMIN_CHAT_ID}")
    for period in PERIODS:
        _, boundary = current_window(period)
        # Отчёт в boundary придёт по окну, которое закроется в этот момент.
        pending_start, pending_end = previous_window(period, boundary)
        log(
            f"  {period}: ближайший отчёт "
            f"{period_label(period, pending_start, pending_end)} в {boundary:%d.%m %H:%M:%S}"
        )
        threading.Thread(target=scheduler, args=(period,), daemon=True).start()

    log("Запуск polling")
    try:
        bot.polling(none_stop=True, skip_pending=True)
    except telebot.apihelper.TelegramConflictError:
        # Telegram отдаёт Conflict, когда за одним токеном уже работает
        # другой процесс с polling. Сообщение объясняет это лучше traceback.
        sys.exit(
            "Этот бот уже запущен в другом процессе. Telegram не даёт двум "
            "ботам с одним токеном читать сообщения одновременно."
        )
    except KeyboardInterrupt:
        log("Остановлен")
