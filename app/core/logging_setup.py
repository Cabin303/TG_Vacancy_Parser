"""Настройка логирования в файл logs/app.log.

Ошибки не «проглатываются»: они всегда попадают в лог с полным контекстом и
дополнительно выводятся в интерфейс.
"""

import logging

from app.core import paths


def setup_logging() -> None:
    paths.ensure_log_dir()

    root = logging.getLogger()
    if root.handlers:
        return

    root.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(paths.LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)