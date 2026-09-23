"""Загрузка и сохранение списка каналов.

Каналы хранятся в channels.txt рядом с приложением: по одному на строку,
пустые строки игнорируются (как в оригинальном main.py).
"""

from pathlib import Path

from app.core.paths import CHANNELS_FILE


def load_channels(path: Path | None = None) -> list[str]:
    file = path or CHANNELS_FILE
    if not file.exists():
        return []
    with file.open("r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def save_channels(channels: list[str], path: Path | None = None) -> None:
    file = path or CHANNELS_FILE
    with file.open("w", encoding="utf-8") as f:
        for channel in channels:
            f.write(channel.strip() + "\n")