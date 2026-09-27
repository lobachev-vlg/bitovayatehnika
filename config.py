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


# id чата, куда бот отправляет отчёты. Узнать свой: написать @userinfobot.
VISITS_ADMIN_CHAT_ID = _int_env("VISITS_ADMIN_CHAT_ID")

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
    problems = list(CONFIG_PROBLEMS) if PLACEHOLDER in REQUESTS_BOT_TOKEN else []
    if PLACEHOLDER in REQUESTS_BOT_TOKEN:
        problems.append(_missing_token_message(REQUESTS_BOT_TOKEN))
    if problems:
        sys.exit("Ошибка конфигурации бота заявок:\n- " + "\n- ".join(problems))
