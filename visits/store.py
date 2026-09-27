"""Хранение посещений сайта (SQLite) и подсчёт людей за час / день / неделю.

Кто этим пользуется:
  * app.py       — пишет визит при каждом заходе на главную страницу;
  * visits/bot.py — читает накопленное и строит отчёты.

Считаем ЛЮДЕЙ, а не просмотры: один IP в пределах периода = один человек,
сколько бы раз он ни перезагрузил страницу.

База в data/visits.db растёт сама и никем не чистится. Записи небольшие,
SQLite такой объём держит легко; при очень большой базе имеет смысл
удалять строки старше года.
"""

import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta

from device import DESKTOP, PHONE, TABLET
from paths import data_file

DB_PATH = data_file("visits.db")

# Порог, после которого вместо списка людей отправляем только число.
LIST_LIMIT = 100

# Периоды, которые умеет считать store.
PERIODS = ("hour", "day", "week")

# Периоды, для которых имеет смысл показывать список людей.
# За неделю по требованию отправляем только число.
LIST_PERIODS = ("hour", "day")

# Ограничения на длины полей. Заголовки приходят от клиента, а ограничить
# их нельзя: без обрезки в базу можно вписать километровый User-Agent.
MAX_IP_LEN = 45
MAX_UA_LEN = 300
MAX_REFERER_LEN = 300
MAX_DEVICE_LEN = 16

# Имя колонки с устройством. Вынесено в константу, потому что используется
# и в схеме, и в миграции для баз, созданных прошлой версией.
DEVICE_COLUMN = "device"

# Грубый признак робота. Отсекаем, чтобы в «людях» не учитывались краулеры.
# Список короткий и его легко расширить; false-positive почти не бывает —
# обычный браузер этих слов в User-Agent не содержит.
BOT_MARKERS = (
    "bot",
    "crawl",
    "spider",
    "slurp",
    "curl",
    "wget",
    "python-requests",
    "httpx",
    "headlesschrome",
    "yandex",
    "uptime",
    "monitoring",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS visits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,          -- когда пришёл визит, unix-время (UTC)
    ip TEXT NOT NULL,          -- с кого пришли
    user_agent TEXT NOT NULL DEFAULT '',
    referer TEXT NOT NULL DEFAULT '',
    device TEXT NOT NULL DEFAULT ''   -- телефон, планшет или компьютер
);
CREATE INDEX IF NOT EXISTS idx_visits_ts ON visits (ts);
CREATE INDEX IF NOT EXISTS idx_visits_ip_ts ON visits (ip, ts);
"""


def _ensure_schema(conn):
    """Создаёт таблицу, если её ещё нет, и дописывает недостающие колонки.

    Проверяем каждый раз, а не по флагу в памяти: если файл базы удалили
    при работающем процессе, следующий запрос не упал бы, а создал схему заново.

    Колонка device могла не появиться, если база создана прошлой версией
    программы. Тогда дописываем её на месте: старые строки сохранятся,
    а в новых она получит пустое значение.
    """
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'visits'"
    ).fetchone()
    if not exists:
        conn.executescript(_SCHEMA)
        return

    columns = {row[1] for row in conn.execute("PRAGMA table_info(visits)")}
    if DEVICE_COLUMN not in columns:
        conn.execute(
            f"ALTER TABLE visits ADD COLUMN {DEVICE_COLUMN} TEXT NOT NULL DEFAULT ''"
        )


@contextmanager
def _db():
    """Открывает соединение с базой и закрывает его на выходе.

    WAL нужен, чтобы сайт писал визиты, пока бот в это время читает отчёты.
    """
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        _ensure_schema(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Готовит базу к работе. Вызывается один раз при старте app.py."""
    with _db() as conn:
        conn.execute("SELECT 1 FROM visits LIMIT 1")


def _clip(text, limit):
    """Обрезает строку до limit символов, чтобы не раздувать базу."""
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def is_probable_bot(user_agent):
    """Похож ли User-Agent на робота. True = скорее всего не человек."""
    text = (user_agent or "").lower()
    return any(marker in text for marker in BOT_MARKERS)


def log_visit(ip, user_agent="", referer="", device=""):
    """Записывает один визит на сайт.

    Возвращает True, если визит записан, False — если отброшен как робот.
    """
    if is_probable_bot(user_agent):
        return False

    with _db() as conn:
        conn.execute(
            "INSERT INTO visits (ts, ip, user_agent, referer, device) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                time.time(),
                _clip(ip, MAX_IP_LEN) or "unknown",
                _clip(user_agent, MAX_UA_LEN),
                _clip(referer, MAX_REFERER_LEN),
                _clip(device, MAX_DEVICE_LEN),
            ),
        )
    return True


def current_window(kind, now=None):
    """Открытый (текущий) период: (начало, конец).

    hour — текущий час, day — сегодня с 00:00, week — неделя с понедельника.
    """
    now = now or datetime.now()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if kind == "hour":
        start = now.replace(minute=0, second=0, microsecond=0)
        return start, start + timedelta(hours=1)
    if kind == "day":
        return midnight, midnight + timedelta(days=1)
    if kind == "week":
        start = midnight - timedelta(days=midnight.weekday())
        return start, start + timedelta(days=7)

    raise ValueError(f"Неизвестный период: {kind}. Допустимо: {', '.join(PERIODS)}")


def previous_window(kind, now=None):
    """Период, который уже закончился: (начало, конец).

    Отчёты отправляем по итогам закрытого периода, поэтому нужен именно он.
    """
    start, end = current_window(kind, now)
    return start - (end - start), start


def period_stats(kind, now=None):
    """Считает закрытый период.

    Возвращает словарь:
      kind         — какой период считали;
      start, end   — границы периода (datetime);
      views        — сколько раз заходили (просмотров);
      unique       — сколько разных людей (IP);
      visitors     — список людей: ip, first_ts, last_ts, hits, user_agent, device;
      devices      — сколько просмотров с телефона, планшета, компьютера.
    """
    start, end = previous_window(kind, now)
    start_ts, end_ts = start.timestamp(), end.timestamp()

    with _db() as conn:
        views = conn.execute(
            "SELECT COUNT(*) FROM visits WHERE ts >= ? AND ts < ?",
            (start_ts, end_ts),
        ).fetchone()[0]

        # Группируем по IP: один человек = одна строка.
        # User-Agent и устройство берём подзапросом от самого свежего визита
        # этого человека, а не MAX(user_agent) — тот выбирался бы сравнением
        # строк и был бы случайным из нескольких устройств.
        rows = conn.execute(
            "SELECT ip, MIN(ts), MAX(ts), COUNT(*), "
            "  (SELECT u.user_agent FROM visits u "
            "    WHERE u.ip = visits.ip AND u.ts >= ? AND u.ts < ? "
            "    ORDER BY u.ts DESC LIMIT 1), "
            "  (SELECT u.device FROM visits u "
            "    WHERE u.ip = visits.ip AND u.ts >= ? AND u.ts < ? "
            "    ORDER BY u.ts DESC LIMIT 1) "
            "FROM visits "
            "WHERE ts >= ? AND ts < ? "
            "GROUP BY ip ORDER BY MIN(ts)",
            (start_ts, end_ts, start_ts, end_ts, start_ts, end_ts),
        ).fetchall()

        # Просмотры по устройствам. Считаем все три ключа всегда, чтобы в
        # отчёте не появлялось и не исчезало устройство вместе с первым визитом.
        counted = dict.fromkeys((PHONE, TABLET, DESKTOP), 0)
        for (device,) in conn.execute(
            "SELECT device FROM visits WHERE ts >= ? AND ts < ?",
            (start_ts, end_ts),
        ):
            counted[device if device in counted else DESKTOP] += 1

    visitors = [
        {
            "ip": row[0],
            "first_ts": row[1],
            "last_ts": row[2],
            "hits": row[3],
            "user_agent": row[4] or "",
            "device": row[5] or "",
        }
        for row in rows
    ]

    return {
        "kind": kind,
        "start": start,
        "end": end,
        "views": views,
        "unique": len(visitors),
        "visitors": visitors,
        "devices": counted,
    }


def short_user_agent(user_agent, limit=48):
    """Короткий User-Agent для строки отчёта — чтобы влезало в сообщение."""
    return _clip(user_agent, limit) or "-"
