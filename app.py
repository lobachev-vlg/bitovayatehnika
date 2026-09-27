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

from flask import Flask, flash, redirect, render_template, request

from config import SECRET_KEY
from orders.store import add_order, init_db as init_orders_db
from paths import data_file
from visits.store import init_db, log_visit

# Поля формы в том же порядке, в котором пишем их в CSV.
FORM_FIELDS = ("name", "phone", "device", "address", "problem")

# Что показывать в сообщении об ошибке, если поле не заполнено.
FIELD_LABELS = {
    "name": "имя",
    "phone": "телефон",
    "device": "прибор",
    "address": "адрес",
    "problem": "описание проблемы",
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
    log_visit(
        client_ip(),
        request.headers.get("User-Agent", ""),
        request.headers.get("Referer", ""),
    )
    return render_template("index.html")


@app.route("/request", methods=["POST"])
def make_request():
    """Приём заявки с формы.

    После отправки отдаём 302 на главную: страница с формой доступна и по
    прямой ссылке (тогда как её рендер засчитался бы ещё одним визитом),
    а сообщение об успехе показывается через flash.
    """
    values = {field: request.form.get(field, "").strip() for field in FORM_FIELDS}
    missing = [FIELD_LABELS[field] for field in FORM_FIELDS if not values[field]]

    if missing:
        flash(f"Заполни: {', '.join(missing)}")
        return redirect("/")

    try:
        # Сначала очередь: из неё бот забирает заявку и отправляет в Telegram.
        # В CSV кладём вторым шагом — это запасной вариант, чтобы заявки
        # можно было прочитать, даже если бот не запущен.
        order_id = add_order(
            name=values["name"],
            phone=values["phone"],
            device=values["device"],
            address=values["address"],
            problem=values["problem"],
            source="site",
        )
    except Exception:
        app.logger.exception("Не удалось положить заявку в очередь")
        flash("Не удалось сохранить заявку. Позвони нам, пожалуйста.")
        return redirect("/")

    try:
        with open(data_file("requests.csv"), "a", encoding="utf-8") as f:
            f.write(",".join(csv_field(values[field]) for field in FORM_FIELDS) + "\n")
    except OSError:
        # CSV — копия для удобства, очередь уже создана, поэтому заявка не теряется.
        app.logger.exception("Заявка #%s не попала в requests.csv", order_id)

    flash(f"Заявка отправлена, номер {order_id}")
    return redirect("/")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # host 0.0.0.0 нужен, чтобы сайт был виден не только с этой машины.
    # debug=False обязателен: с ним Werkzeug показывает отладочный отчёт
    # и выполняет консоль любому, кто зашёл снаружи.
    app.run(host="0.0.0.0", port=port, debug=False)
