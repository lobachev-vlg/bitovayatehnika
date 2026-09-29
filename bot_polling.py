"""Общие мелочи для Telegram-ботов: запуск polling и разбор его ошибок.

Отдельный модуль, потому что оба бота (visits и orders) страдают от одного и
того же и должны вести себя одинаково: одна и та же ошибка, одно и то же
сообщение и одна и та же причина.
"""

from telebot.apihelper import ApiTelegramException

# Telegram отдаёт 409, когда за одним токеном уже работает другой процесс
# с polling. Отдельного класса исключения для этого в pyTelegramBotAPI нет,
# поэтому конфликт опознаётся по коду ошибки — это работает во всех версиях.
CONFLICT_ERROR_CODE = 409

# Подсказка по поиску и снятию лишнего процесса. Само сообщение Telegram
# («make sure that only one bot instance is running») ничего не говорит о том,
# что делать, а конфликт возникает у людей регулярно: достаточно оставить
# второе окно с run.py открытым.
CONFLICT_HINT = (
    "\n\nЧто делать: закрой лишнее окно, где запущен run.py или этот бот.\n"
    "  Windows — найти и снять:\n"
    "    tasklist /FI \"IMAGENAME eq python.exe\"\n"
    "    taskkill /PID <номер> /F\n"
    "  Linux: ps aux | grep 'visits.bot\\|orders.bot', затем kill <номер>"
)


def conflict_message(bot_label):
    """Что сказать пользователю, если бот уже запущен в другом процессе.

    bot_label — человеческое имя бота («бот посещений»), чтобы в сообщении
    было видно, о ком речь.
    """
    return (
        f"{bot_label.capitalize()} уже запущен в другом процессе.\n"
        f"  Telegram не даёт двум ботам с одним токеном читать сообщения "
        f"одновременно, и второй молча отваливается."
        f"{CONFLICT_HINT}"
    )


def is_polling_conflict(error):
    """True, если ошибка — конфликт polling, а не что-то другое.

    Раньше здесь ловили telebot.apihelper.TelegramConflictError, но такого
    класса в библиотеке нет: вместо понятного сообщения вылетал
    AttributeError на самом except, и настоящая причина терялась.
    """
    return isinstance(error, ApiTelegramException) and (
        getattr(error, "error_code", None) == CONFLICT_ERROR_CODE
    )
