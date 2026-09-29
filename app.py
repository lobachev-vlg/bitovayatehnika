"""Сайт «Ремонт бытовой техники».

Две задачи:
  1. показать главную страницу и принять заявку;
  2. записать каждый заход на сайт в data/visits.db, откуда их забирает
     visits/bot.py для отчётов.

Заявка попадает сразу в два места:
  * data/orders.db  — очередь: её забирает orders/bot.py и шлёт в Telegram;
  * data/requests.csv — обычный текстовый файл, чтобы заявки можно было
    прочитать и без Telegram.

Запуск:
    python app.py            # http://127.0.0.1:5000
    PORT=8080 python app.py  # другой порт
"""

import os
import time

from flask import Flask, Response, flash, redirect, render_template, request, url_for

from config import (
    SECRET_KEY,
    SITE_PHONE_DISPLAY,
    SITE_PHONE_TEL,
    site_base_url,
)
from device import detect_device
from orders.store import add_order, init_db as init_orders_db
from paths import data_file
from services import SERVICES, is_known, title_for
from visits.store import init_db, log_visit

# Поля формы в том же порядке, в котором пишем их в CSV.
FORM_FIELDS = ("name", "phone", "device", "address", "problem")

# Обязательные поля. Адрес и описание проблемы необязательны: человек
# может не знать адрес (например, звонит с чужого телефона) или ещё не
# понять, что сломалось, — и не должен терять заявку из-за пустых полей.
REQUIRED_FIELDS = ("name", "phone", "device")

# Их наличие в форме не проверяем. Порядок совпадает с FORM_FIELDS: по нему
# пишется CSV, и пропуск поля сдвинул бы колонки.
OPTIONAL_FIELDS = ("address", "problem")

# Что показывать в сообщении об ошибке, если поле не заполнено.
FIELD_LABELS = {
    "name": "имя",
    "phone": "телефон",
    "device": "прибор",
    "address": "адрес",
    "problem": "описание проблемы",
}

# Тексты страниц ошибок. Ключ — код ответа.
ERROR_PAGES = {
    404: {
        "title": "Страница не найдена",
        "text": "Такой страницы нет — возможно, в адресе опечатка или ссылка устарела.",
    },
    500: {
        "title": "Сайт не отвечает",
        "text": "Что-то сломалось на нашей стороне. Попробуйте обновить страницу "
                "или позвонить — заявку примем и по телефону.",
    },
}

app = Flask(__name__)
app.secret_key = SECRET_KEY

if SECRET_KEY == "change-me":
    app.logger.warning(
        "SECRET_KEY не задан: сообщения об отправке формы перестанут работать "
        "после перезапуска. Задай переменную окружения SECRET_KEY."
    )

init_db()
init_orders_db()


def template_context(**extra):
    """Общие для всех страниц значения: телефон, устройство, адрес сайта.

    Заведены здесь, чтобы номер не расходился между шапкой, подвалом,
    мобильной панелью и микроразметкой.
    """
    context = {
        "phone_display": SITE_PHONE_DISPLAY,
        "phone_tel": SITE_PHONE_TEL,
        "device": detect_device(request.headers.get("User-Agent", "")),
        "base_url": site_base_url(request.host_url),
        # Список приборов общий для карточек услуг и для выпадающего списка
        # в форме: в двух местах он обязан совпадать.
        "services": SERVICES,
    }
    context.update(extra)
    return context


def structured_data(base_url):
    """Микроразметка Schema.org: чем занимаемся, когда работаем, сколько стоит.

    Яндекс и Google показывают её расширенным сниппетом — телефон, часы
    работы и диапазон цен прямо в выдаче.

    Адрес и город сюда не вписаны: SITE_URL по умолчанию — заглушка, а
    названия города в проекте нет. Когда появится, добавь address и
    areaServed: в разметке они заметно улучшают локальную выдачу.
    """
    return {
        "@context": "https://schema.org",
        "@type": "LocalBusiness",
        "name": "МастерДом",
        "description": (
            "Ремонт бытовой техники на дому: стиральные машины, холодильники, "
            "плиты, посудомойки, микроволновки, кондиционеры."
        ),
        "url": base_url,
        "image": f"{base_url}{url_for('static', filename='img/hero-master.svg')}",
        "telephone": SITE_PHONE_TEL,
        "priceRange": "700–5000 ₽",
        "openingHoursSpecification": {
            "@type": "OpeningHoursSpecification",
            "dayOfWeek": [
                "Monday", "Tuesday", "Wednesday", "Thursday",
                "Friday", "Saturday", "Sunday",
            ],
            "opens": "08:00",
            "closes": "22:00",
        },
    }


def client_ip():
    """IP посетителя.

    Сначала берём X-Forwarded-For — за nginx/Cloudflare там настоящий адрес.
    Заголовок подделывается клиентом, так что для публичного сайта за прокси
    имеет смысл брать не первый элемент, а доверять только своему прокси.
    """
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def csv_field(value):
    """Готовит значение к записи в CSV.

    Двойные кавычки внутри удваиваем, иначе значение развалит строку CSV.
    Значения, с которых Excel и LibreOffice читают формулу (=cmd|...), ставим
    в кавычки с апострофом — иначе файл откроется и выполнит их.
    """
    text = value.replace('"', '""')
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r")):
        text = "'" + text
    return f'"{text}"'


@app.route("/")
def index():
    """Главная страница. Каждый заход на неё засчитывается как визит."""
    user_agent = request.headers.get("User-Agent", "")

    log_visit(
        client_ip(),
        user_agent,
        request.headers.get("Referer", ""),
        detect_device(user_agent),
    )
    context = template_context()
    return render_template(
        "index.html",
        # Шаблон по data-device решает, показывать ли панель с быстрым звонком
        # и крупные кнопки: на телефоне это удобнее, на компьютере лишнее.
        canonical_url=f"{context['base_url']}{url_for('index')}",
        structured_data=structured_data(context["base_url"]),
        **context,
    )


@app.route("/sitemap.xml")
def sitemap():
    """Карта сайта для поисковиков.

    Страница одна, но карту всё равно стоит отдавать: Яндекс и Google
    заходят на /sitemap.xml без всякой догадки о структуре сайта.
    Дата изменения — не время ответа, а mtime шаблона на диске: так дата
    меняется, только когда правят вёрстку.
    """
    template_mtime = os.path.getmtime(
        os.path.join(app.root_path, app.template_folder, "index.html")
    )
    lastmod = time.strftime("%Y-%m-%d", time.localtime(template_mtime))
    location = f"{site_base_url(request.host_url)}{url_for('index')}"

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        "  <url>\n"
        f"    <loc>{location}</loc>\n"
        f"    <lastmod>{lastmod}</lastmod>\n"
        "    <changefreq>weekly</changefreq>\n"
        "    <priority>1.0</priority>\n"
        "  </url>\n"
        "</urlset>\n"
    )
    return Response(xml, mimetype="application/xml")


@app.route("/robots.txt")
def robots():
    """robots.txt. Всё открыто: закрывать поисковикам нечего."""
    base = site_base_url(request.host_url)
    return Response(
        "User-agent: *\n"
        "Allow: /\n\n"
        f"Sitemap: {base}{url_for('sitemap')}\n",
        mimetype="text/plain",
    )


@app.route("/request", methods=["POST"])
def make_request():
    """Приём заявки с формы.

    После отправки отдаём 302 на главную: страница с формой доступна и по
    прямой ссылке (тогда как её рендер засчитался бы ещё одним визитом),
    а сообщение об успехе показывается через flash.
    """
    values = {field: request.form.get(field, "").strip() for field in FORM_FIELDS}
    missing = [FIELD_LABELS[field] for field in REQUIRED_FIELDS if not values[field]]

    if missing:
        flash(f"Заполни: {', '.join(missing)}")
        return redirect("/")

    # Прибор приходит как code из списка услуг. Значение можно подделать
    # в обход формы, поэтому проверяем по справочнику, а не на вид.
    if not is_known(values["device"]):
        flash("Выбери прибор из списка")
        return redirect("/")

    try:
        # Сначала очередь: из неё бот забирает заявку и отправляет в Telegram.
        # В CSV кладём вторым шагом — это запасной вариант, чтобы заявки
        # можно было прочитать, даже если бот не запущен.
        order_id = add_order(
            name=values["name"],
            phone=values["phone"],
            # В очередь кладём название прибора, а не code: очередь и CSV
            # читает человек, и «Стиральные машины» понятнее, чем «washing».
            device=title_for(values["device"]),
            address=values["address"],
            problem=values["problem"],
            source="site",
        )
    except Exception:
        app.logger.exception("Не удалось положить заявку в очередь")
        flash("Не удалось сохранить заявку. Позвони нам, пожалуйста.")
        return redirect("/")

    try:
        # В CSV пишем то же, что в очередь, иначе две копии заявки
        # разошлись бы по содержанию.
        row = dict(values, device=title_for(values["device"]))
        with open(data_file("requests.csv"), "a", encoding="utf-8") as f:
            f.write(",".join(csv_field(row[field]) for field in FORM_FIELDS) + "\n")
    except OSError:
        # CSV — копия для удобства, очередь уже создана, поэтому заявка не теряется.
        app.logger.exception("Заявка #%s не попала в requests.csv", order_id)

    flash(f"Заявка отправлена, номер {order_id}")
    return redirect("/")


def render_error(code):
    """Показывает свою страницу вместо служебной Werkzeug.

    Шаблон намеренно ничего не берёт из базы: страница 500 как раз и значит,
    что с хранилищем что-то не так, и обращение к нему из обработчика
    утянуло бы за собой вторую ошибку.
    """
    page = ERROR_PAGES[code]
    return (
        render_template(
            "error.html",
            code=code,
            title=page["title"],
            text=page["text"],
            phone_display=SITE_PHONE_DISPLAY,
            phone_tel=SITE_PHONE_TEL,
        ),
        code,
    )


@app.errorhandler(404)
def not_found(error):
    """Страница не найдена."""
    return render_error(404)


@app.errorhandler(500)
def server_error(error):
    """Внутренняя ошибка сервера.

    Саму ошибку не показываем посетителю, но пишем в лог: без этого
    поломка видна только по словам пользователя.
    """
    app.logger.exception("Ошибка 500 на %s", request.path)
    return render_error(500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # host 0.0.0.0 нужен, чтобы сайт был виден не только с этой машины.
    # debug=False обязателен: с ним Werkzeug показывает отладочный отчёт
    # и выполняет консоль любому, кто зашёл снаружи.
    app.run(host="0.0.0.0", port=port, debug=False)
