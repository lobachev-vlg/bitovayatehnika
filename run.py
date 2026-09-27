"""Единая точка входа: запускает сайт и обоих ботов одной командой.

Запуск всего сразу:
    python run.py

Запуск по частям:
    python run.py site        # только сайт
    python run.py visits      # только бот статистики посещений
    python run.py orders      # только бот заявок
    python run.py site visits # сайт и бот посещений

Почему каждый компонент стартует отдельным процессом, а не потоком:
  * падение одного не роняет остальные — сайт продолжит принимать заявки,
    даже если упал бот;
  * боты и сайт не мешают друг другу в памяти;
  * логи видно по отдельности, с префиксом компонента.

Ctrl+C (или остановка окна) останавливает все процессы разом.
"""

import os
import subprocess
import sys
import threading

from config import check_requests_config, check_visits_config
from paths import ROOT_DIR

# Имя команды -> (аргументы для python, подпись в логах).
COMPONENTS = {
    "site": (["app.py"], "сайт"),
    "visits": (["-m", "visits.bot"], "бот посещений"),
    "orders": (["-m", "orders.bot"], "бот заявок"),
}

# Проверка настроек перед стартом: чтобы не поднимать три процесса и сразу
# упасть, лучше показать одно понятное сообщение.
PREFLIGHT = {
    "visits": check_visits_config,
    "orders": check_requests_config,
}


def force_utf8_console():
    """Заставляет собственный вывод писать в UTF-8.

    Нужно только когда вывод уходит в файл или канал: при перенаправлении
    Python на Windows берёт кодировку консоли (обычно cp1252) и кириллица
    молча превращается в «?». К настоящей консоли это не относится — там
    Windows передаёт текст через свой API и всё читается.
    """
    if hasattr(sys.stdout, "reconfigure") and not sys.stdout.isatty():
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def log(component, message):
    print(f"[{component}] {message}", flush=True)


def pump(stream, component):
    """Пересылает строки из процесса в консоль с префиксом компонента.

    -u при запуске отключает буферизацию, иначе строки появлялись бы
    пачками и лог выглядел бы «зависшим».
    """
    for line in iter(stream.readline, ""):
        line = line.rstrip()
        if line:
            log(component, line)


def start(name, args):
    """Запускает один компонент и возвращает процесс.

    PYTHONIOENCODING обязателен: вывод ребёнка идёт в канал, а не в консоль,
    и без этого кириллица в логах превращается в «?».
    """
    argv_args, label = COMPONENTS[name]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-u", *argv_args],
        cwd=ROOT_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    threading.Thread(target=pump, args=(process.stdout, label), daemon=True).start()
    log(label, f"запущен, pid={process.pid}")
    return name, process


def main(selected):
    """Поднимает выбранные компоненты и ждёт их завершения."""
    for name in selected:
        for check in [PREFLIGHT[name]] if name in PREFLIGHT else []:
            check()

    started = [start(name, COMPONENTS[name][0]) for name in selected]
    log("run", f"работают компоненты: {', '.join(selected)}")
    log("run", "остановить — Ctrl+C")

    try:
        while True:
            for name, process in list(started):
                code = process.poll()
                if code is None:
                    continue
                started.remove((name, process))
                label = COMPONENTS[name][1]
                if code == 0:
                    log(label, "завершился")
                else:
                    # Не перезапускаем: скорее всего, не заполнены настройки,
                    # и молчаливый цикл перезапусков только засорит консоль.
                    log(label, f"упал с кодом {code}. Исправь причину и запусти снова.")
    except KeyboardInterrupt:
        print("", flush=True)
        log("run", "останавливаю компоненты")
    finally:
        for name, process in started:
            if process.poll() is None:
                process.terminate()
        for name, process in started:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        log("run", "остановлено")


if __name__ == "__main__":
    force_utf8_console()
    requested = sys.argv[1:] or list(COMPONENTS)
    unknown = [name for name in requested if name not in COMPONENTS]
    if unknown:
        sys.exit(
            f"Неизвестный компонент: {', '.join(unknown)}. "
            f"Доступно: {', '.join(COMPONENTS)}"
        )
    main(requested)
