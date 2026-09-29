"""Разбор ошибок polling.

Тест появился из-за реальной поломки: код ловил
telebot.apihelper.TelegramConflictError, но такого класса в
pyTelegramBotAPI нет. Вместо понятного сообщения вылетал AttributeError на
самой строке except, и настоящая причина — конфликт с другим процессом —
терялась в трассировке.
"""

import pytest
from telebot.apihelper import ApiTelegramException

from bot_polling import CONFLICT_ERROR_CODE, conflict_message, is_polling_conflict


def api_error(code, description="описание"):
    """Исключение Telegram с заданным кодом, как его создаёт библиотека."""
    return ApiTelegramException(
        "getUpdates", "", {"error_code": code, "description": description}
    )


def test_conflict_is_detected_by_code():
    error = api_error(CONFLICT_ERROR_CODE, "terminated by other getUpdates request")
    assert is_polling_conflict(error) is True


@pytest.mark.parametrize("code", [400, 401, 403, 404, 429, 500, 502])
def test_other_api_errors_are_not_conflicts(code):
    """Конфликт polling — не то же самое, что любая ошибка API.

    Если спутать, то вместо 400 «chat not found» пользователю скажут, что
    бот запущен дважды, и он пойдёт искать несуществующий процесс.
    """
    assert is_polling_conflict(api_error(code)) is False


def test_foreign_exception_is_not_conflict():
    assert is_polling_conflict(ValueError("что-то другое")) is False
    assert is_polling_conflict(RuntimeError()) is False


def test_exception_without_error_code_is_not_conflict():
    """Объект, у которого error_code нет, — тоже не повод считать его
    конфликтом: getattr по умолчанию даёт None, и сравнение не проходит."""
    class Broken(Exception):
        pass

    assert is_polling_conflict(Broken()) is False


def test_conflict_message_explains_the_cause_and_the_fix():
    message = conflict_message("бот посещений")

    assert "Бот посещений" in message
    # Причина и что делать: сообщение Telegram само по себе бесполезно.
    assert "уже запущен в другом процессе" in message
    assert "Что делать" in message
    assert "taskkill" in message


def test_conflict_message_mentions_its_own_bot():
    assert "Бот заявок" in conflict_message("бот заявок")
    assert "Бот посещений" in conflict_message("бот посещений")
