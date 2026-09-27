"""Хранилище посещений: что пишется, что считается и как старая база
доживает до новой версии.

Отдельный файл неслучаен: visits/store.py отвечает за миграцию схемы, и
именно её ломали при добавлении колонки device. Проверка на готовой старой
базе ниже повторяет тот случай.
"""

import sqlite3
import time
from datetime import datetime, timedelta

import pytest

from device import DESKTOP, PHONE, TABLET
from visits import store

# ---------- роботы ----------

@pytest.mark.parametrize(
    "user_agent",
    [
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "Mozilla/5.0 (compatible; YandexBot/3.0)",
        "python-requests/2.31.0",
        "curl/8.4.0",
        "Mozilla/5.0 (Linux; Android 13) Chrome/120.0 headlessChrome/120.0",
    ],
)
def test_bots_are_not_counted(user_agent):
    assert store.is_probable_bot(user_agent) is True


@pytest.mark.parametrize(
    "user_agent",
    [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148 Safari/604.1",
        "",
        None,
    ],
)
def test_people_are_not_taken_for_bots(user_agent):
    assert store.is_probable_bot(user_agent) is False


def test_log_visit_drops_bots(visits_db_path):
    """Запись робота не должна попадать в базу."""
    before = _visits_total(visits_db_path)
    assert store.log_visit("1.2.3.4", "Googlebot/2.1") is False
    assert _visits_total(visits_db_path) == before


def test_log_visit_saves_device(visits_db_path):
    store.log_visit("1.2.3.4", "Mozilla/5.0 (Windows NT 10.0) Chrome/120", device=PHONE)

    with sqlite3.connect(visits_db_path) as conn:
        device = conn.execute(
            "SELECT device FROM visits ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]

    assert device == PHONE


# ---------- обрезка длинных значений ----------

def test_long_user_agent_is_trimmed(visits_db_path):
    store.log_visit("1.2.3.4", "x" * 5000)

    with sqlite3.connect(visits_db_path) as conn:
        length = conn.execute("SELECT LENGTH(user_agent) FROM visits ORDER BY id DESC LIMIT 1").fetchone()[0]

    assert length <= store.MAX_UA_LEN


def test_newlines_in_user_agent_are_flattened(visits_db_path):
    """Перевод строки в User-Agent сломал бы отчёт в Telegram."""
    store.log_visit("1.2.3.4", "Mozilla/5.0\nChrome/120\r\nTail")

    with sqlite3.connect(visits_db_path) as conn:
        agent = conn.execute("SELECT user_agent FROM visits ORDER BY id DESC LIMIT 1").fetchone()[0]

    assert "\n" not in agent and "\r" not in agent


# ---------- миграция ----------

def test_old_database_gains_device_column(tmp_path):
    """База, созданная прошлой версией, должна получить колонку device
    без потери уже записанных строк.

    Сценарий реальный: у человека в проекте уже накоплена статистика, и
    после обновления программа обязана продолжить с ней работать.
    """
    old_db = tmp_path / "visits.db"
    with sqlite3.connect(old_db) as conn:
        conn.executescript(
            """
            CREATE TABLE visits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                ip TEXT NOT NULL,
                user_agent TEXT NOT NULL DEFAULT '',
                referer TEXT NOT NULL DEFAULT ''
            );
            """
        )
        conn.execute(
            "INSERT INTO visits (ts, ip, user_agent, referer) VALUES (?, ?, ?, ?)",
            (time.time(), "9.9.9.9", "старый визит", ""),
        )

    with sqlite3.connect(old_db) as conn:
        store._ensure_schema(conn)

        columns = {row[1] for row in conn.execute("PRAGMA table_info(visits)")}
        rows = conn.execute("SELECT ip, user_agent, device FROM visits").fetchall()

    assert "device" in columns
    assert rows == [("9.9.9.9", "старый визит", "")]


def test_ensure_schema_is_idempotent(tmp_path):
    """Повторный вызов не должен ни падать, ни плодить колонки."""
    fresh = tmp_path / "fresh.db"
    with sqlite3.connect(fresh) as conn:
        store._ensure_schema(conn)
        store._ensure_schema(conn)

        columns = [row[1] for row in conn.execute("PRAGMA table_info(visits)")]

    assert columns.count("device") == 1


def test_schema_is_recreated_after_file_deletion(tmp_path, monkeypatch):
    """Если файл базы удалили при работающей программе, следующий визит
    должен создать базу заново, а не упасть с «unable to open database».

    Такое бывает, когда someone чистит data/ вручную, не останавливая сайт.
    Своя база в tmp_path нужна ещё и потому, что общая база тестов после
    этого проверки стала бы непригодной.
    """
    db_path = tmp_path / "visits.db"
    monkeypatch.setattr(store, "DB_PATH", db_path)
    assert store.log_visit("1.2.3.4", "Chrome/120") is True

    db_path.unlink()
    assert store.log_visit("5.5.5.5", "Chrome/120") is True

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM visits").fetchone()[0] == 1


# ---------- статистика ----------

def test_period_stats_counts_one_person_per_ip(own_visits_db):
    """Люди считаются по IP, а не по просмотрам: десять перезагрузок —
    это один человек."""
    now = _insert_visits([("5.5.5.5", DESKTOP, 3)])

    stats = store.period_stats("day", now=now)

    assert stats["views"] == 3
    assert stats["unique"] == 1
    assert stats["visitors"][0]["hits"] == 3


def test_period_stats_splits_by_device(own_visits_db):
    now = _insert_visits(
        [
            ("1.1.1.1", PHONE, 2),
            ("2.2.2.2", DESKTOP, 1),
            ("3.3.3.3", TABLET, 1),
        ]
    )

    stats = store.period_stats("day", now=now)

    assert stats["devices"] == {PHONE: 2, TABLET: 1, DESKTOP: 1}


def test_period_stats_always_has_all_three_devices(own_visits_db):
    """Все три ключа присутствуют всегда, даже без единого визита:
    иначе строка в отчёте то появляется, то исчезает."""
    stats = store.period_stats("day", now=datetime.now())

    assert set(stats["devices"]) == {PHONE, TABLET, DESKTOP}


def test_period_stats_ignores_open_period(own_visits_db):
    """В отчёт попадает закрытый период, а не текущий: иначе числа
    каждый час менялись бы задним числом."""
    now = datetime.now()
    _insert_visits([("4.4.4.4", DESKTOP, 1)], period="hour", now=now)
    _insert_visits([("5.5.5.5", DESKTOP, 1)], period="hour", now=now, current=True)

    stats = store.period_stats("hour", now=now)

    assert [visitor["ip"] for visitor in stats["visitors"]] == ["4.4.4.4"]


def test_period_stats_takes_device_from_latest_visit(own_visits_db):
    """Человек мог сначала зайти с телефона, потом с компьютера. В отчёте
    показываем то, с чего он зашёл последним."""
    now = datetime.now()
    start, end = store.previous_window("day", now)
    span = end - start

    _insert_at("6.6.6.6", PHONE, start + span * 0.25)
    _insert_at("6.6.6.6", DESKTOP, start + span * 0.75)

    stats = store.period_stats("day", now=now)

    assert stats["visitors"][0]["device"] == DESKTOP
    assert stats["visitors"][0]["hits"] == 2


# ---------- окна ----------

def test_previous_window_is_the_one_before_current():
    current_start, current_end = store.current_window("hour")
    start, end = store.previous_window("hour")

    assert (start, end) == (current_start - (current_end - current_start), current_start)


def test_day_window_starts_at_midnight():
    start, _ = store.current_window("day")

    assert (start.hour, start.minute, start.second) == (0, 0, 0)


def test_unknown_period_is_rejected():
    with pytest.raises(ValueError):
        store.current_window("year")


# ---------- помощники ----------

def _visits_total(db_path):
    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM visits").fetchone()[0]


def _insert_at(ip, device, moment):
    """Один визит с заданным временем.

    log_visit всегда ставит текущее время, поэтому здесь мы пишем строку
    сами: period_stats считает закрытый период, и визит должен лежать
    именно в нём, а не «где-то пару часов назад».
    """
    with sqlite3.connect(store.DB_PATH) as conn:
        conn.execute(
            "INSERT INTO visits (ts, ip, user_agent, referer, device) "
            "VALUES (?, ?, ?, ?, ?)",
            (moment.timestamp() if hasattr(moment, "timestamp") else moment,
             ip, "Chrome/120", "", device),
        )


def _insert_visits(rows, period="day", now=None, current=False):
    """Кладёт визиты в середину окна периода и возвращает «сейчас».

    По умолчанию — в закрытое окно, то есть ровно то, что попадёт в отчёт.
    current=True кладёт в текущий, открытый период: так проверяется, что
    он в отчёт не попадает.
    """
    now = now or datetime.now()
    start, end = store.current_window(period, now) if current else store.previous_window(period, now)
    moment = start + (end - start) / 2

    for ip, device, count in rows:
        for _ in range(count):
            _insert_at(ip, device, moment)

    return now
