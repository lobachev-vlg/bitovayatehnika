"""Определение устройства по User-Agent.

Отдельный модуль без зависимостей, поэтому проверяется parametetrize:
один тест — один User-Agent, и при появлении новой разновидности
достаточно дописать строку в таблицу.
"""

import pytest

from device import DESKTOP, PHONE, TABLET, detect_device, device_label

IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
ANDROID_PHONE = (
    "Mozilla/5.0 (Linux; Android 13; SM-A536E) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Mobile Safari/537.36"
)
IPAD = (
    "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.0 Mobile/15E148 Safari/604.1"
)
ANDROID_TABLET = (
    "Mozilla/5.0 (Linux; Android 13; SM-X710) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
KINDLE = (
    "Mozilla/5.0 (Linux; U; Android 4.0.3; en-us; KFTT Build/IML74K) Silk/3.68 "
    "like Chrome/39.0 Mobile Safari/537.36"
)
WINDOWS_CHROME = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
MAC_SAFARI = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
WINDOWS_PHONE = (
    "Mozilla/5.0 (Windows Phone 10.0; Android 6.0.1; Microsoft; Lumia 950) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/52.0 Mobile Safari/537.36 Edge/15"
)


@pytest.mark.parametrize(
    ("user_agent", "expected"),
    [
        (IPHONE, PHONE),
        (ANDROID_PHONE, PHONE),
        (WINDOWS_PHONE, PHONE),
        (IPAD, TABLET),
        (ANDROID_TABLET, TABLET),
        (KINDLE, TABLET),
        (WINDOWS_CHROME, DESKTOP),
        (MAC_SAFARI, DESKTOP),
    ],
)
def test_detect_device(user_agent, expected):
    assert detect_device(user_agent) == expected


def test_android_tablet_is_not_a_phone():
    """Android-планшет отличить можно только по отсутствию «mobile» в строке.

    Если бы он проверялся как телефон, планшет получил бы телефонную
    липкую панель — с кнопками не по размеру пальца.
    """
    assert "mobile" not in ANDROID_TABLET.lower()
    assert detect_device(ANDROID_TABLET) == TABLET


@pytest.mark.parametrize("empty", ["", "   ", None])
def test_empty_user_agent_is_desktop(empty):
    """Пустой агент — это компьютер: урезанная вёрстка никому не нужна."""
    assert detect_device(empty) == DESKTOP


def test_detection_ignores_case():
    assert detect_device("IPHONE") == PHONE


def test_device_label_for_every_known_device():
    for name in (PHONE, TABLET, DESKTOP):
        assert device_label(name)


def test_device_label_of_unknown_value_falls_back_to_desktop():
    """Значение из базы может оказаться чем-то новым: отчёт не должен падать."""
    assert device_label("smart-tv") == device_label(DESKTOP)
