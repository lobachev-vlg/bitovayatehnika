"""Определение устройства посетителя по строке User-Agent.

Зачем: телефон и компьютер отличаются не только шириной окна. На телефоне
уместнее крупные кнопки и липкая панель с звонком, на компьютере — обычная
шапка. Разница выводится в шаблон как data-device у <html>, и по нему
работают стили.

Возвращает одно из: PHONE, TABLET, DESKTOP.
"""

# Планшет проверяем раньше телефона: у Kindle Silk в строке есть «Mobile»,
# поэтому порядок проверок важен.
TABLET = "tablet"
PHONE = "phone"
DESKTOP = "desktop"

# Слова, по которым устройство опознаётся как планшет.
_TABLET_MARKERS = ("ipad", "tablet", "kindle", "silk", "playbook", "nexus 7", "nexus 10")

# Слова, по которым устройство опознаётся как телефон.
# Android здесь нет: у Android-планшетов в строке нет «mobile», и их ловит
# отдельная проверка ниже.
_PHONE_MARKERS = (
    "iphone",
    "ipod",
    "windows phone",
    "iemobile",
    "blackberry",
    "bb10",
    "opera mini",
    "opera mobi",
    "mobile safari",
    "fennec",
    "webos",
    "symbian",
    "nokia",
)

# Как называть устройство в отчётах.
DEVICE_LABELS = {
    PHONE: "телефон",
    TABLET: "планшет",
    DESKTOP: "компьютер",
}


def detect_device(user_agent):
    """Возвращает PHONE, TABLET или DESKTOP по строке User-Agent.

    Пустая строка и незнакомые браузеры считаем компьютером: показывать
    телефону урезанную версию страницы из-за нераспознанного агента хуже,
    чем показать обычную.
    """
    ua = (user_agent or "").strip().lower()
    if not ua:
        return DESKTOP

    if any(marker in ua for marker in _TABLET_MARKERS):
        return TABLET
    # Android-планшет — единственный, у кого нет «mobile» в строке.
    if "android" in ua and "mobile" not in ua:
        return TABLET

    if any(marker in ua for marker in _PHONE_MARKERS) or "mobile" in ua:
        return PHONE

    return DESKTOP


def device_label(device):
    """Человеческое название устройства для отчётов."""
    return DEVICE_LABELS.get(device, DEVICE_LABELS[DESKTOP])
