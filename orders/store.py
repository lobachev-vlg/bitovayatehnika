"""Очередь заявок с сайта (SQLite) — промежуточное хранилище между сайтом и ботом.

Зачем очередь, а не отправка сразу из app.py:
  * сайт не должен зависеть от Telegram — при падении сети он всё равно
    обязан принять заявку;
  * если Telegram недоступен, заявка ждёт и уходит при следующей попытке;
  * номер заявки и статус («прочитано» / «перезвонить») переживают
    перезапуск бота, потому что лежат в базе, а не в памяти.

Кто этим пользуется:
  * app.py       — кладёт заявку в очередь (add_order);
  * orders/bot.py — разбирает очередь и шлёт заявки в Telegram.
"""

import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from html import escape

from paths import data_file

DB_PATH = data_file("orders.db")

# Статусы заявки по порядку её жизни:
#   new   — принята, ещё не ушла в Telegram (лежит в очереди);
#   sent  — ушла в Telegram, ждёт реакции владельца;
#   read  — владелец нажал «Прочитано»;
#   called— владелец нажал «Перезвонить».
# Очередь отправки — это только status = new. Если оставить отправленные
# в статусе new, бот будет слать одну и ту же заявку по кругу.
STATUS_NEW = "new"
STATUS_SENT = "sent"
STATUS_READ = "read"
STATUS_CALLED = "called"
STATUSES = (STATUS_NEW, STATUS_SENT, STATUS_READ, STATUS_CALLED)

# Статусы, после которых кнопки под заявкой больше не нужны.
FINAL_STATUSES = (STATUS_READ, STATUS_CALLED)

# Ограничения на длины полей: значения приходят из формы, а ограничить их нельзя.
MAX_NAME_LEN = 120
MAX_PHONE_LEN = 40
MAX_DEVICE_LEN = 200
MAX_ADDRESS_LEN = 300
MAX_PROBLEM_LEN = 2000

# Пауза перед повторной попыткой отправки, секунды. Растёт с числом неудач,
# чтобы при лежащем Telegram бот не долбил API каждую секунду.
RETRY_BASE_SECONDS = 15
RETRY_MAX_SECONDS = 600

_SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,   -- он же номер заявки для человека
    ts REAL NOT NULL,                      -- когда пришла, unix-время
    name TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    device TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    problem TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'site',   -- откуда пришла
    status TEXT NOT NULL DEFAULT 'new',    -- new / read / called
    sent_at REAL,                          -- когда ушла в Telegram
    telegram_message_id INTEGER,           -- id сообщения: по нему правим кнопки
    attempts INTEGER NOT NULL DEFAULT 0,   -- сколько раз не удалось отправить
    last_attempt REAL                      -- когда последний раз пробовали
);
CREATE INDEX IF NOT EXISTS idx_orders_queue ON orders (status, id);
"""

# Список колонок для SELECT — один раз, чтобы не расходились в четырёх запросах.
_COLUMNS = (
    "id, ts, name, phone, device, address, problem, source, status, "
    "sent_at, telegram_message_id, attempts, last_attempt"
)


def _ensure_schema(conn):
    """Создаёт таблицу, если её ещё нет (и создаём заново после удаления файла)."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'orders'"
    ).fetchone()
    if not exists:
        conn.executescript(_SCHEMA)


@contextmanager
def _db():
    """Открывает соединение и закрывает его на выходе.

    WAL обязателен: сайт пишет заявки, бот в это время читает очередь.
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
        conn.execute("SELECT 1 FROM orders LIMIT 1")


def _clip(text, limit):
    """Обрезает строку и убирает переводы строк — из них собирается сообщение."""
    return " ".join((text or "").split())[:limit]


def add_order(name, phone, device, address, problem, source="site"):
    """Кладёт заявку в очередь. Возвращает её номер (id)."""
    with _db() as conn:
        cursor = conn.execute(
            "INSERT INTO orders (ts, name, phone, device, address, problem, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                time.time(),
                _clip(name, MAX_NAME_LEN),
                _clip(phone, MAX_PHONE_LEN),
                _clip(device, MAX_DEVICE_LEN),
                _clip(address, MAX_ADDRESS_LEN),
                _clip(problem, MAX_PROBLEM_LEN),
                _clip(source, 40) or "site",
            ),
        )
        return cursor.lastrowid


def _row_to_dict(row):
    """Превращает строку из SELECT в словарь — так удобнее читать в коде."""
    columns = (
        "id", "ts", "name", "phone", "device", "address", "problem",
        "source", "status", "sent_at", "telegram_message_id",
        "attempts", "last_attempt",
    )
    return dict(zip(columns, row))


def _rows(sql, params=()):
    """Выборка с закрытым соединением.

    Соединение держим только на время чтения: на Windows незакрытая
    блокировка не даст удалить файл базы и мешает боту и сайту работать.
    """
    with _db() as conn:
        return conn.execute(sql, params).fetchall()


def pending(limit=20, now=None):
    """Заявки, которые ещё не ушли в Telegram и пора повторить.

    Свежие (last_attempt = NULL) берём сразу. Неудачные — только когда прошла
    пауза перед повтором, чтобы не долбить Telegram по нескольку раз в секунду.
    """
    now = time.time() if now is None else now
    rows = _rows(
        f"SELECT {_COLUMNS} FROM orders WHERE status = ? ORDER BY id LIMIT 500",
        (STATUS_NEW,),
    )

    ready = []
    for row in rows:
        order = _row_to_dict(row)
        if order["last_attempt"] is None:
            ready.append(order)
        else:
            # Пауза растёт: 15 с, 30 с, 60 с... и не выше RETRY_MAX_SECONDS,
            # чтобы при лежащем Telegram бот не долбил API.
            wait = min(
                RETRY_MAX_SECONDS,
                RETRY_BASE_SECONDS * (2 ** max(order["attempts"] - 1, 0)),
            )
            if now - order["last_attempt"] >= wait:
                ready.append(order)
        if len(ready) >= limit:
            break
    return ready


def mark_sent(order_id, telegram_message_id):
    """Заявка ушла в Telegram: переводим в sent, из очереди она исчезает."""
    now = time.time()
    with _db() as conn:
        conn.execute(
            "UPDATE orders SET status = ?, sent_at = ?, telegram_message_id = ?, "
            "       attempts = 0, last_attempt = ? WHERE id = ?",
            (STATUS_SENT, now, telegram_message_id, now, order_id),
        )


def mark_failed(order_id):
    """Отправка не удалась: считаем попытку и пробуем позже."""
    now = time.time()
    with _db() as conn:
        conn.execute(
            "UPDATE orders SET attempts = attempts + 1, last_attempt = ? WHERE id = ?",
            (now, order_id),
        )


def set_status(order_id, status):
    """Меняет статус по нажатию кнопки. Возвращает заявку или None."""
    if status not in STATUSES:
        raise ValueError(f"Неизвестный статус: {status}. Допустимо: {', '.join(STATUSES)}")
    with _db() as conn:
        conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
    return get_order(order_id)


def get_order(order_id):
    """Заявка по номеру или None."""
    rows = _rows(f"SELECT {_COLUMNS} FROM orders WHERE id = ?", (order_id,))
    return _row_to_dict(rows[0]) if rows else None


def recent(limit=10):
    """Последние заявки — для команды /orders."""
    rows = _rows(f"SELECT {_COLUMNS} FROM orders ORDER BY id DESC LIMIT ?", (limit,))
    return [_row_to_dict(row) for row in rows]


def queue_size():
    """Сколько заявок ждут отправки — для /orders и проверок."""
    with _db() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM orders WHERE status = ?", (STATUS_NEW,)
        ).fetchone()[0]


def format_order(order, status_line=None):
    """Текст заявки для Telegram в HTML-разметке.

    HTML нужен, чтобы телефон стал кликабельным. Все значения от пользователя
    обязательно экранируются: иначе символы вроде <b> в имени сломали бы
    разметку сообщения, и Telegram его бы не показал.
    """
    name = escape(order["name"] or "—")
    phone_raw = (order["phone"] or "").strip()
    phone = escape(phone_raw) if phone_raw else "—"
    # tel: работает и на мобильном (откроет dialer), и на десктопе.
    phone_line = f'📞 <a href="tel:{escape(phone_raw)}">{phone}</a>' if phone_raw else f"📞 {phone}"

    lines = [
        f"<b>Новая заявка #{order['id']}</b>",
        f"🕐 <i>{format_time(order['ts'])}</i>",
        f"👤 {name}",
        phone_line,
        f"🔧 {escape(order['device'] or '—')}",
        f"📍 {escape(order['address'] or '—')}",
        f"📝 {escape(order['problem'] or '—')}",
        f"🌐 Источник: {escape(order['source'] or '—')}",
    ]
    if status_line:
        lines.append("")
        lines.append(status_line)
    return "\n".join(lines)


def format_time(ts):
    """Время заявки в виде 27.09.2026 18:04:22."""
    return datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M:%S")
