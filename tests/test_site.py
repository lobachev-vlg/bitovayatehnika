"""Проверки сайта: главная, приём заявки, SEO-файлы, страницы ошибок.

Именно эти тесты ловят то, что случилось с проектом однажды: в репозиторий
попали маркеры слияния git, app.py перестал импортироваться, и сайт был
полностью сломан — заметил это только человек. Тест на код 200 упал бы
сразу.
"""

import csv
import json
import re
import sqlite3

import pytest

from app import FORM_FIELDS, OPTIONAL_FIELDS, REQUIRED_FIELDS
from services import SERVICES

PHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

FORM = {
    "name": "Пётр",
    "phone": "+7 900 000-00-00",
    # Прибор приходит code из services.py, а в очередь попадает его название.
    "device": "washing",
    "address": "ул. Ленина, 1",
    "problem": "Не сливает воду",
}


def orders_count(db_path):
    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]


def visits_rows(db_path):
    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT ip, device FROM visits ORDER BY id").fetchall()


# ---------- главная ----------

def test_index_returns_200(client):
    assert client.get("/").status_code == 200


def test_index_renders_whole_page(client):
    """Страница должна собраться целиком, а не только открыться.

    Ошибка в шаблоне (забытая переменная, сломанный тег) даёт 500, но
    проверка кода ответа на главной это уже не поймает — нужен признак,
    что в разметке есть ключевые блоки.
    """
    body = client.get("/").get_data(as_text=True)
    for marker in ("МастерДом", "Отправить заявку", "Частые вопросы", "</html>"):
        assert marker in body, f"нет фрагмента {marker!r}"


def test_index_sets_device_from_user_agent(client):
    body = client.get("/", headers={"User-Agent": PHONE_UA}).get_data(as_text=True)
    assert 'data-device="phone"' in body

    body = client.get("/", headers={"User-Agent": DESKTOP_UA}).get_data(as_text=True)
    assert 'data-device="desktop"' in body


def test_index_writes_visit_with_device(client, visits_db_path):
    before = len(visits_rows(visits_db_path))
    client.get("/", headers={"User-Agent": PHONE_UA})

    rows = visits_rows(visits_db_path)
    assert len(rows) == before + 1
    assert rows[-1][1] == "phone"


# ---------- приём заявки ----------

def test_request_creates_order(client, orders_db_path):
    before = orders_count(orders_db_path)

    response = client.post("/request", data=FORM, follow_redirects=True)

    assert response.status_code == 200
    assert orders_count(orders_db_path) == before + 1
    assert "Заявка отправлена" in response.get_data(as_text=True)


def test_request_saves_all_fields(client, orders_db_path):
    client.post("/request", data=FORM)

    with sqlite3.connect(orders_db_path) as conn:
        row = conn.execute(
            "SELECT name, phone, device, address, problem, source, status "
            "FROM orders ORDER BY id DESC LIMIT 1"
        ).fetchone()

    assert row == (
        FORM["name"], FORM["phone"], "Стиральные машины",
        FORM["address"], FORM["problem"], "site", "new",
    )


def test_request_stores_device_title_not_code(client, orders_db_path):
    """В очередь кладётся название прибора, а не его code: очередь читает
    человек, и «Стиральные машины» понятнее, чем «washing»."""
    client.post("/request", data=FORM)

    with sqlite3.connect(orders_db_path) as conn:
        device = conn.execute(
            "SELECT device FROM orders ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]

    assert device == "Стиральные машины"


def test_request_without_optional_fields_is_accepted(client, orders_db_path):
    """Адрес и описание проблемы необязательны: человек может не знать
    адрес или ещё не понять, что сломалось."""
    before = orders_count(orders_db_path)

    response = client.post(
        "/request",
        data={"name": "Пётр", "phone": "+7 900 000-00-00", "device": "washing"},
        follow_redirects=True,
    )

    assert "Заявка отправлена" in response.get_data(as_text=True)
    assert orders_count(orders_db_path) == before + 1

    with sqlite3.connect(orders_db_path) as conn:
        address, problem = conn.execute(
            "SELECT address, problem FROM orders ORDER BY id DESC LIMIT 1"
        ).fetchone()

    # Пустые строки, а не None: колонки объявлены NOT NULL.
    assert address == ""
    assert problem == ""


def test_request_without_optional_fields_writes_empty_cells_in_csv(client, csv_path):
    """CSV остаётся с пятью колонками, иначе строки разъедутся."""
    client.post("/request", data={"name": "Пётр", "phone": "+7 900 000-00-00", "device": "fridge"})

    with open(csv_path, encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))

    assert len(rows[-1]) == len(FORM_FIELDS)
    assert rows[-1][FORM_FIELDS.index("address")] == ""
    assert rows[-1][FORM_FIELDS.index("device")] == "Холодильники"


@pytest.mark.parametrize("field", REQUIRED_FIELDS)
def test_request_requires_each_required_field(client, orders_db_path, field):
    """Каждое обязательное поле проверяется по отдельности."""
    before = orders_count(orders_db_path)
    data = {**FORM, field: ""}

    response = client.post("/request", data=data, follow_redirects=True)

    assert orders_count(orders_db_path) == before
    assert "Заполни" in response.get_data(as_text=True)


@pytest.mark.parametrize("field", OPTIONAL_FIELDS)
def test_optional_fields_are_not_required_in_html(client, field):
    """Адрес и описание не должны мешать отправке и в самом браузере."""
    body = client.get("/").get_data(as_text=True)
    tag = re.search(rf'name="{field}"[^>]*', body).group(0)
    assert "required" not in tag


def test_request_rejects_device_outside_the_list(client, orders_db_path):
    """Значение select можно подделать в обход формы — принимаем только
    приборы из services.py, иначе в очередь попадёт мусор."""
    before = orders_count(orders_db_path)

    response = client.post(
        "/request",
        data={**FORM, "device": "<script>alert(1)</script>"},
        follow_redirects=True,
    )

    assert orders_count(orders_db_path) == before
    assert "Выбери прибор из списка" in response.get_data(as_text=True)


def test_form_offers_exactly_the_services_from_the_catalogue(client):
    """Список в форме и карточки услуг берутся из services.py, поэтому
    разойтись не могут — проверяем, что оба места на месте."""
    body = client.get("/").get_data(as_text=True)
    # Первый option — пустое значение без кавычек, поэтому берём любой текст
    # между value=" и ", включая пустую строку.
    options = re.findall(r'<option value="([^"]*)"', body)

    assert options == [""] + [s["code"] for s in SERVICES]
    # Подпись option собирается в шаблоне, поэтому сверяем её с эталоном
    # здесь, а не ищем в вёрстке.
    for service in SERVICES:
        assert f'{service["title"]} — {service["price"]}' in body


def test_request_trims_whitespace(client, orders_db_path):
    client.post("/request", data={**FORM, "name": "  Пётр  ", "phone": " +7 900 000-00-00 "})

    with sqlite3.connect(orders_db_path) as conn:
        name, phone = conn.execute(
            "SELECT name, phone FROM orders ORDER BY id DESC LIMIT 1"
        ).fetchone()

    assert name == "Пётр"
    assert phone == "+7 900 000-00-00"


def test_request_get_is_not_allowed(client):
    """Форма отправляется POST-ом; GET на тот же адрес — ошибка метода."""
    assert client.get("/request").status_code == 405


# ---------- CSV ----------

def test_csv_keeps_quotes_and_commas_intact(client, csv_path):
    """Значение с запятой и кавычками не должно развалить строку CSV.

    Проверяем на problem: device принимает только значения из списка
    услуг, а любое другое отклоняется ещё до записи.
    """
    tricky = 'Не сливает, "очень тихо"'
    client.post("/request", data={**FORM, "problem": tricky})

    # Заголовка в файле нет: это выгрузка для чтения глазами, а не таблица
    # для импорта. Поэтому читаем позициями в порядке FORM_FIELDS.
    with open(csv_path, encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))

    # Без экранирования значение развалилось бы на две ячейки.
    assert rows[-1][FORM_FIELDS.index("problem")] == tricky
    assert len(rows[-1]) == len(FORM_FIELDS)


def test_csv_neutralises_spreadsheet_formulas(client, csv_path):
    """Значение, с которого Excel читает формулу, должно попасть в файл
    с апострофом — иначе файл откроется и выполнит его."""
    client.post("/request", data={**FORM, "name": "=cmd|'/c calc'!A1"})

    with open(csv_path, encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))

    assert rows[-1][FORM_FIELDS.index("name")].startswith("'")


# ---------- SEO (пункт 8) ----------

def test_sitemap_is_valid_xml_with_home_page(client):
    response = client.get("/sitemap.xml")

    assert response.status_code == 200
    assert response.mimetype == "application/xml"
    body = response.get_data(as_text=True)
    assert body.startswith('<?xml version="1.0"')
    assert "<loc>" in body and "/</loc>" in body
    assert re.search(r"<lastmod>\d{4}-\d{2}-\d{2}</lastmod>", body)


def test_robots_points_to_sitemap(client):
    response = client.get("/robots.txt")

    assert response.status_code == 200
    assert response.mimetype == "text/plain"
    assert "Sitemap: http://localhost/sitemap.xml" in response.get_data(as_text=True)


def test_canonical_url_is_present(client):
    body = client.get("/").get_data(as_text=True)
    assert '<link rel="canonical" href="http://localhost/">' in body


def test_structured_data_is_valid_json(client):
    body = client.get("/").get_data(as_text=True)
    match = re.search(
        r'<script type="application/ld\+json">(.*?)</script>', body, re.S
    )

    assert match, "микроразметка не найдена"
    data = json.loads(match.group(1))
    assert data["@type"] == "LocalBusiness"
    assert data["telephone"].startswith("+7")
    assert data["openingHoursSpecification"]["opens"] == "08:00"


# ---------- страницы ошибок (пункт 4) ----------

def test_404_shows_own_page(client):
    response = client.get("/нет-такой-страницы")

    assert response.status_code == 404
    body = response.get_data(as_text=True)
    assert "Страница не найдена" in body
    # Служебная страница Werkzeug не должна просачиваться наружу.
    assert "Werkzeug" not in body


def test_404_links_back_home(client):
    body = client.get("/нет-такой-страницы").get_data(as_text=True)
    assert 'href="/"' in body


def test_500_shows_own_page(client, boom_route):
    response = client.get(boom_route)

    assert response.status_code == 500
    body = response.get_data(as_text=True)
    assert "Сайт не отвечает" in body
    # Текст настоящей ошибки посетителю не показываем.
    assert "проверка страницы ошибки" not in body


def test_error_pages_are_not_indexed(client):
    """Страница ошибки в поиск не должна попадать."""
    body = client.get("/нет-такой-страницы").get_data(as_text=True)
    assert 'name="robots" content="noindex"' in body


# ---------- телефон в одном месте ----------

def test_phone_comes_from_config(client):
    """Номер выводится переменной, а не зашит в шаблон: смена номера в
    config.py меняет его и в шапке, и в микроразметке."""
    from config import SITE_PHONE_DISPLAY, SITE_PHONE_TEL

    body = client.get("/").get_data(as_text=True)
    assert f"tel:{SITE_PHONE_TEL}" in body
    assert SITE_PHONE_DISPLAY in body
    assert "+7 900 123-45-67" not in body or SITE_PHONE_DISPLAY == "+7 900 123-45-67"


# ---------- защита от повторов ----------

def test_two_orders_get_different_numbers(client, orders_db_path):
    """Номер заявки должен расти: по нему клиент и владелец её узнают."""
    before = orders_count(orders_db_path)
    client.post("/request", data=FORM)
    client.post("/request", data=FORM)

    with sqlite3.connect(orders_db_path) as conn:
        ids = [row[0] for row in conn.execute("SELECT id FROM orders ORDER BY id")]

    new_ids = ids[-2:]
    assert len(new_ids) == 2
    assert new_ids[0] != new_ids[1]
    assert orders_count(orders_db_path) == before + 2
