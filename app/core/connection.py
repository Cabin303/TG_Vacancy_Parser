"""Мониторинг соединения: интернет и доступность Telegram.

Работает без блокировки GUI: проверки выполняются в фоновом потоке
(ConnectionMonitor.run_once), результаты приходят callback'ом. Наличие
сетевого интерфейса НЕ считается признаком интернета — проверяется реальный
HTTP-ответ публичного хоста.
"""

import logging
import threading
import time
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)

INTERNET_PROBE_URL = "https://www.iana.org"
TELEGRAM_PROBE_URL = "https://telegram.me"
DEFAULT_TIMEOUT = 8
DEFAULT_INTERVAL = 20

_COLORS = {
    "green": "#2e8b57",
    "yellow": "#c9a100",
    "red": "#cc0000",
}


@dataclass
class ConnectionState:
    """internet/telegram: True / False / None (неизвестно, идёт проверка)."""

    internet: bool | None = None
    telegram: bool | None = None

    @property
    def label(self) -> str:
        if self.internet is False:
            return "Интернет: нет соединения"
        if self.internet is None:
            return "Проверка соединения..."
        if self.telegram is True:
            return "Интернет: OK | Telegram: OK"
        return "Интернет: OK | Telegram: недоступен"

    @property
    def color(self) -> str:
        if self.internet is False:
            return _COLORS["red"]
        if self.internet is True and self.telegram is True:
            return _COLORS["green"]
        return _COLORS["yellow"]

    def usable_for_parser(self) -> bool:
        return self.internet is True and self.telegram is True


def _probe(url: str, timeout: int) -> bool:
    """True, если хост отвечает HTTP (любой код) — канал связи есть."""
    try:
        requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=timeout,
            allow_redirects=False,
        )
        return True
    except (requests.RequestException, OSError) as e:
        log.info("Недоступно %s: %s", url, e)
        return False


def check_connection(timeout: int = DEFAULT_TIMEOUT, probe=None) -> ConnectionState:
    """Проверяет интернет, затем Telegram. probe(url, timeout) -> bool (для тестов)."""
    probe = probe or _probe
    internet = probe(INTERNET_PROBE_URL, timeout)
    if not internet:
        return ConnectionState(internet=False, telegram=None)
    telegram = probe(TELEGRAM_PROBE_URL, timeout)
    return ConnectionState(internet=True, telegram=telegram)


class ConnectionMonitor:
    """Периодические проверки соединения с защитой от параллельных запусков."""

    def __init__(self, interval: int = DEFAULT_INTERVAL, check=None):
        self.interval = interval
        self.check = check or check_connection
        self._last = 0.0
        self._in_flight = False

    def due(self, now=None) -> bool:
        """True, когда пора запустить следующую проверку (не чаще interval)."""
        if self._in_flight:
            return False
        now = now if now is not None else time.monotonic()
        return (now - self._last) >= self.interval

    def begin_check(self, now=None) -> bool:
        if self._in_flight:
            return False
        self._in_flight = True
        self._last = now if now is not None else time.monotonic()
        return True

    def finish_check(self) -> None:
        self._in_flight = False

    def run_once(self, timeout: int = DEFAULT_TIMEOUT, on_result=None) -> bool:
        """Запускает проверку в потоке; on_result(state) — по завершении (в потоке)."""
        if not self.begin_check():
            return False

        def work():
            try:
                state = self.check(timeout=timeout)
                if on_result:
                    on_result(state)
            finally:
                self.finish_check()

        threading.Thread(target=work, daemon=True).start()
        return True