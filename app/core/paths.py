"""Верные пути проекта.

Никакой зависимости от текущей рабочей директории: все пути строятся
относительно реального расположения файлов приложения. Это важно для macOS:
/Volumes/..., пробелы и кириллица в пути не должны ломать работу.
"""

import os
from pathlib import Path

# app/core/paths.py -> TG_Vacancy_Parser
BASE_DIR = Path(__file__).resolve().parent.parent.parent

RESULT_FILE = BASE_DIR / "telegram_found_posts.txt"
SEEN_FILE = BASE_DIR / "seen_posts.json"
SETTINGS_FILE = BASE_DIR / "gui_settings.json"
CHANNELS_FILE = BASE_DIR / "channels.txt"
FILTERS_FILE = BASE_DIR / "vacancy_filters.json"

LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "app.log"

DEFAULT_SAVE_DIR = BASE_DIR


def ensure_log_dir() -> Path:
    LOG_DIR.mkdir(exist_ok=True)
    return LOG_DIR


def result_file_for(save_dir) -> Path:
    """Файл результата Parser лежит в корне выбранной папки сохранения."""
    return Path(save_dir) / "telegram_found_posts.txt"


def save_dir_status(path) -> tuple[bool, str]:
    """Проверка папки сохранения перед записью результата.

    Возвращает (можно ли использовать, пояснение). Не падает с traceback,
    если папки больше не существует.
    """
    target = Path(path)
    if not target.exists() or not target.is_dir():
        return False, "Папка сохранения недоступна. Выберите другую папку."
    if not os.access(target, os.W_OK):
        return False, "Папка сохранения недоступна. Выберите другую папку."
    probe = target / ".write_probe.tmp"
    try:
        with probe.open("w", encoding="utf-8") as f:
            f.write("ok")
        probe.unlink()
        return True, ""
    except OSError:
        return False, "Папка сохранения недоступна. Выберите другую папку."