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
    or "8856463579:AAGAzfjoJkI1pjws96St97udT-qMYmOevHc"
)

# Токен бота, который принимает заявки в Telegram (папка orders/).
REQUESTS_BOT_TOKEN = (
    os.environ.get("REQUESTS_BOT_TOKEN", "").strip()
    or "8927607812:AAGmYLzSaxrKeg8B7kt9tr_2Bu1KVug_CmU"
)


def _int_env(name, default=0):
    """Читает целое число из переменной окружения.

    Пустое значение даёт default. Нечисловое записывается в CONFIG_PROBLEMS
    и тоже даёт default: молча уехавший не туда id чата опаснее явной ошибки,
    но ронять импорт нельзя — ошибку покажет check_visits_config().

    Если в name пришло число, значит перепутали место: значение положили
    первым аргументом вместо имени переменной. Раньше такая ошибка
    выглядела как «id не задан», и приходилось гадать, где он потерялся.
    """
    if name.strip().lstrip("+-").isdigit():
        raise ValueError(
            f"_int_env() ждёт ИМЯ переменной окружения, а получено число {name!r}. "
            f"Значение передаётся вторым аргументом: "
            f"_int_env('VISITS_ADMIN_CHAT_ID', {name.strip()})"
        )

    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        CONFIG_PROBLEMS.append(f"{name} должна быть числом, получено: {raw!r}")
        return default


# id чата, куда бот отправляет отчёты о посещениях. Узнать свой: @userinfobot.
# Первым аргументом — имя переменной окружения, вторым — значение на случай,
# если переменная не задана. На сервере задавай через окружение, здесь прописано.
VISITS_ADMIN_CHAT_ID = _int_env("VISITS_ADMIN_CHAT_ID", 5035329122)

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


def chat_access_error(bot, chat_id):
    """Проверяет, что бот может писать в чат. Возвращает текст проблемы или None.

    Отдельная проверка потому, что id может быть верным, а чат всё равно
    недоступен: бот не может написать пользователю, пока тот сам не начал
    с ним диалог. Telegram в этом случае отвечает «chat not found», и без
    этой проверки пришлось бы расшифровывать ошибку по логу ночью.

    Ничего не выходит и ничего не чинит: бот должен запуститься и ждать,
    а не падать из-за того, что чат ещё не открыт.
    """
    try:
        bot.get_chat(chat_id)
    except Exception as error:
        hint = "Открой своего бота в Telegram, нажми /start и перезапусти его."
        try:
            username = bot.get_me().username
        except Exception:
            username = None
        if username:
            hint = f"Открой @{username}, нажми /start и перезапусти бота."
        return (
            f"Бот не может писать в чат {chat_id}: {error}\n"
            f"  Если id получен у @userinfobot, то он верный, но бот ещё не"
            f" начал с тобой диалог.\n"
            f"  {hint}"
        )
    return None


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
