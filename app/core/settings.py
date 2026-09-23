"""Единый конфигурационный слой приложения.

Файл настроек остаётся gui_settings.json (сохраняется совместимость), но теперь
он один отвечает и за Parser (папка сохранения результатов), и за Splitter
(постов в файле, авто-запуск). Секретов здесь нет — приложение не использует
Telegram API и не хранит никаких credentials.
"""

import json
import logging

from app.core import paths

log = logging.getLogger(__name__)

DEFAULT_SETTINGS = {
    "save_dir": str(paths.DEFAULT_SAVE_DIR),
    "posts_per_file": 10,
    "auto_split": True,
}


def load_settings() -> dict:
    settings = dict(DEFAULT_SETTINGS)
    try:
        if paths.SETTINGS_FILE.exists():
            with paths.SETTINGS_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for key, value in data.items():
                    if key in DEFAULT_SETTINGS:
                        settings[key] = value
    except (OSError, ValueError) as e:
        log.warning("Не удалось прочитать настройки %s: %s", paths.SETTINGS_FILE, e)
    return settings


def save_settings(settings: dict) -> None:
    to_save = {key: settings.get(key, default) for key, default in DEFAULT_SETTINGS.items()}
    try:
        with paths.SETTINGS_FILE.open("w", encoding="utf-8") as f:
            json.dump(to_save, f, ensure_ascii=False, indent=4)
    except OSError as e:
        log.error("Не удалось сохранить настройки %s: %s", paths.SETTINGS_FILE, e)
        raise