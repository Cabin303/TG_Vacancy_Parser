"""Поисковые фразы (вакансии) хранятся в отдельном файле vacancy_filters.json.

Этой пары файлов достаточно: код не содержит списка фраз, пользователь
управляет списком из GUI, и при первом запуске новые настройки переносят
существующие фразы из legacy-списка (не заменяя их пустым набором).
"""

import json
import logging
from pathlib import Path

from app.core.paths import FILTERS_FILE
from app.parser.keywords import KEYWORDS

log = logging.getLogger(__name__)


def normalize_entries(raw, default_enabled: bool = True) -> list:
    """Приводит произвольные данные к схеме [{"name", "enabled"}], отбрасывая мусор."""
    entries = []
    items = raw if isinstance(raw, list) else []
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"].strip():
            entries.append(
                {
                    "name": item["name"].strip(),
                    "enabled": bool(item.get("enabled", default_enabled)),
                }
            )
    return entries


def legacy_entries() -> list:
    return [{"name": name, "enabled": True} for name in KEYWORDS]


def migrate(file: Path) -> list:
    """Первый запуск: копируем существующие фильтры из кода в файл настроек.

    Никогда не создаём пустой список вместо существующих фраз.
    """
    entries = legacy_entries()
    file.parent.mkdir(parents=True, exist_ok=True)
    with file.open("w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=4)
    log.info("Создан %s: %d фраз перенесены из конфигурации приложения", file.name, len(entries))
    return entries


def load_filters(path=None) -> list:
    file = Path(path or FILTERS_FILE)
    if not file.exists():
        return migrate(file)
    try:
        with file.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError) as e:
        log.warning("Файл фильтров повреждён (%s): %s — используем прежний список", file, e)
        return legacy_entries()
    return normalize_entries(raw)


def save_filters(entries, path=None) -> None:
    file = Path(path or FILTERS_FILE)
    data = normalize_entries(entries)
    with file.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def active_names(entries) -> list:
    return [e["name"] for e in entries if e.get("enabled")]


def add_filter(entries, name: str) -> list:
    out = [dict(e) for e in entries]
    out.append({"name": name.strip(), "enabled": True})
    return out


def update_filter(entries, index: int, name: str) -> list:
    out = [dict(e) for e in entries]
    out[index]["name"] = name.strip()
    return out


def remove_filter(entries, index: int) -> list:
    return [e for i, e in enumerate(entries) if i != index]


def toggle_filter(entries, index: int) -> list:
    out = [dict(e) for e in entries]
    out[index]["enabled"] = not out[index]["enabled"]
    return out