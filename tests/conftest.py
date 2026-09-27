"""Общая настройка тестов.

Самое важное здесь — переменная DATA_DIR: она выставляется до того, как
тесты импортируют app. Пути к базам вычисляются в момент импорта
visits/store.py и orders/store.py, поэтому подменить папку позже, в
фикстуре, уже не получится — тесты писали бы в настоящие data/visits.db
и data/orders.db и портили бы рабочую статистику.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent

# Корень проекта в sys.path: тесты запускаются из папки tests/, и без этого
# импорт app не нашёл бы соседние модули.
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

_TMP_DATA_DIR = tempfile.mkdtemp(prefix="masterdom-tests-")
os.environ["DATA_DIR"] = _TMP_DATA_DIR

import pytest  # noqa: E402  — импорт после настройки путей, так и задумано

from app import app as flask_app  # noqa: E402
from orders.store import DB_PATH as ORDERS_DB  # noqa: E402
from paths import data_file  # noqa: E402
from visits import store as visits_store  # noqa: E402
from visits.store import DB_PATH as VISITS_DB  # noqa: E402


# Маршрут, который всегда падает, для проверки страницы ошибки.
# Регистрируется прямо при импорте conftest, а не в фикстуре: Flask
# запрещает добавлять маршруты после первого обработанного запроса,
# а к моменту работы фикстуры тесты уже походили по сайту.
BOOM_PATH = "/_boom"


def _boom():
    raise RuntimeError("проверка страницы ошибки")


flask_app.add_url_rule(BOOM_PATH, "boom", _boom)


@pytest.fixture(scope="session", autouse=True)
def cleanup_data_dir():
    """Удаляет временную папку после всех тестов."""
    yield
    shutil.rmtree(_TMP_DATA_DIR, ignore_errors=True)


@pytest.fixture(scope="session")
def app():
    """Приложение для тестов. Настройки из config.py — заглушки, токены
    ботов для проверки сайта не нужны."""
    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture()
def client(app):
    """Тестовый клиент: запросы идут внутрь процесса, сеть не нужна."""
    return app.test_client()


@pytest.fixture()
def visits_db_path():
    """Путь к базе посещений — тесты читают её напрямую."""
    return VISITS_DB


@pytest.fixture()
def orders_db_path():
    """Путь к очереди заявок."""
    return ORDERS_DB


@pytest.fixture()
def csv_path():
    """Путь к выгрузке заявок в CSV."""
    return data_file("requests.csv")


@pytest.fixture()
def own_visits_db(tmp_path, monkeypatch):
    """Отдельная пустая база посещений для теста.

    Общая база накапливает визиты из всех тестов подряд, и проверять точные
    счётчики в ней нельзя: соседний тест добавил бы свои строки. Такие
    тесты получают свою базу и считают в ней с нуля.
    """
    db_path = tmp_path / "visits.db"
    monkeypatch.setattr(visits_store, "DB_PATH", db_path)
    # Схему создаём сразу: тесты пишут в базу напрямую, минуя store.log_visit.
    visits_store.init_db()
    return db_path


@pytest.fixture()
def boom_route(app):
    """Маршрут, который всегда падает: нужен для проверки страницы 500.

    TESTING=True заставляет Flask не ловить исключения, а отдавать их
    тесту. Для проверки страницы ошибки это как раз мешает, поэтому
    распространение исключений на время вызова выключается, а потом
    возвращается обратно — чтобы настоящие ошибки в других тестах
    по-прежнему были видны.
    """
    app.config["PROPAGATE_EXCEPTIONS"] = False
    yield BOOM_PATH
    app.config["PROPAGATE_EXCEPTIONS"] = None
