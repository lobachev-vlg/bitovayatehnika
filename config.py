"""Настройки проекта: токены Telegram-ботов, id чата для отчётов, ключ Flask.

Каждое значение можно задать двумя способами:
  1. переменной окружения — удобно на сервере, не нужно править код;
  2. вписать прямо в этот файл — удобно локально.

Перед запуском проверь, что токены заполнены:
    python -c "from config import check_visits_config, check_requests_config; check_visits_config(); check_requests_config()"
"""

import os
import sys

# Маркер, по которому понимаем, что значение ещё не заменено на настоящее.
PLACEHOLDER = "ВСТАВЬ_"

# Проблемы, найденные при чтении настроек. Собираются здесь, а не приводят
# к sys.exit сразу: импорт config.py не должен ронять процесс, иначе
# пользователь не увидит все проблемы разом, а только первую.
CONFIG_PROBLEMS = []

# Токен бота со статистикой посещений.
# Держим вид "123456:AAH..." — с двоеточием: telebot проверяет формат при
# создании бота и без двоеточия падает с невнятным ValueError раньше,
# чем сработает check_visits_config() с нормальным сообщением.
VISITS_BOT_TOKEN = (
    os.environ.get("VISITS_BOT_TOKEN", "").strip()
    or "0:ВСТАВЬ_СЮДА_ТОКЕН_БОТА_ДЛЯ_ПОСЕЩЕНИЙ"
)

# Токен бота, который принимает заявки в Telegram (папка orders/).
REQUESTS_BOT_TOKEN = (
    os.environ.get("REQUESTS_BOT_TOKEN", "").strip()
    or "0:ВСТАВЬ_СЮДА_ТОКЕН_БОТА_ДЛЯ_ЗАЯВОК"
)


def _int_env(name, default=0):
    """Читает целое число из переменной окружения.

    Пустое значение даёт default. Нечисловое записывается в CONFIG_PROBLEMS
    и тоже даёт default: молча уехавший не туда id чата опаснее явной ошибки,
    но ронять импорт нельзя — ошибку покажет check_visits_config().
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        CONFIG_PROBLEMS.append(f"{name} должна быть числом, получено: {raw!r}")
        return default


# id чата, куда бот отправляет отчёты о посещениях. Узнать свой: @userinfobot.
VISITS_ADMIN_CHAT_ID = _int_env("VISITS_ADMIN_CHAT_ID")

# id чата, куда уходят заявки с сайта. Обычно то же, что и у отчётов.
# Часто это id группового чата: заявки могут приходить из разных аккаунтов.
ORDERS_ADMIN_CHAT_ID = _int_env("ORDERS_ADMIN_CHAT_ID", VISITS_ADMIN_CHAT_ID)

# Адрес сайта. Бот подставляет его в ответ, когда ему пишут пользователи.
SITE_URL_DEFAULT = "https://example.com"
SITE_URL = os.environ.get("SITE_URL", "").strip() or SITE_URL_DEFAULT

# Телефон сервиса. Держим его здесь, а не в шаблоне: он нужен в трёх видах —
# для показа («+7 900 123-45-67»), для ссылки tel: («+79001234567») и для
# микроразметки Schema.org. В шаблоне на одной странице он повторялся пять раз,
# и при смене номера легко было забыть одно из мест.
SITE_PHONE_DISPLAY = os.environ.get("SITE_PHONE_DISPLAY", "").strip() or "+7 900 123-45-67"
SITE_PHONE_TEL = os.environ.get("SITE_PHONE_TEL", "").strip() or "+79001234567"


def site_base_url(request_fallback=""):
    """Адрес сайта для канонической ссылки, sitemap и микроразметки.

    Пока SITE_URL не задан, стоит заглушка example.com — подставлять её в
    разметку нельзя, поисковики сочтут канонический адрес чужим. Тогда
    берётся хост текущего запроса.
    """
    if SITE_URL and SITE_URL != SITE_URL_DEFAULT:
        return SITE_URL.rstrip("/")
    return (request_fallback or "").rstrip("/")

# Ключ подписи cookie-сессий. Через него работают сообщения об отправке формы.
# На сервере обязательно задай свой, иначе после перезапуска сообщения "слетают".
SECRET_KEY = os.environ.get("SECRET_KEY", "").strip() or "change-me"


def _missing_token_message(token):
    return (
        f"Токен не задан. Впиши его в config.py или задай переменную окружения.\n"
        f"  Сейчас: {token!r}\n"
        f"  Токен берётся у @BotFather командой /newbot"
    )


def check_visits_config():
    """Проверяет настройки бота статистики. При плохих настройках выходит.

    Ничего не возвращает: это проверка перед стартом, а не запрос значения.
    """
    problems = list(CONFIG_PROBLEMS)
    if PLACEHOLDER in VISITS_BOT_TOKEN:
        problems.append(_missing_token_message(VISITS_BOT_TOKEN))
    if VISITS_ADMIN_CHAT_ID == 0:
        problems.append(
            "VISITS_ADMIN_CHAT_ID не задан. Узнать свой chat_id можно у @userinfobot, "
            "потом впиши его в config.py или задай переменную окружения."
        )
    if problems:
        sys.exit("Ошибка конфигурации бота посещений:\n- " + "\n- ".join(problems))


def check_requests_config():
    """Проверяет настройки бота заявок (папка orders/)."""
    problems = list(CONFIG_PROBLEMS)
    if PLACEHOLDER in REQUESTS_BOT_TOKEN:
        problems.append(_missing_token_message(REQUESTS_BOT_TOKEN))
    if ORDERS_ADMIN_CHAT_ID == 0:
        problems.append(
            "ORDERS_ADMIN_CHAT_ID не задан: боту некуда слать заявки. "
            "Узнать chat_id можно у @userinfobot (для группы — добавь бота в неё "
            "и напиши что-нибудь, id будет в group)."
        )
    if problems:
        sys.exit("Ошибка конфигурации бота заявок:\n- " + "\n- ".join(problems))
