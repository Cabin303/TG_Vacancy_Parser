#!/usr/bin/env python3
"""Точка входа единого приложения Telegram Vacancy Parser + Splitter.

Использование:
  python main.py                     — графический интерфейс
  python main.py --parse             — только парсинг (без GUI)
  python main.py --split <файл>      — только разбиение (без GUI)
  python main.py --full              — полный цикл (без GUI)

Путь определяется по расположению файла, а не по рабочей директории.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())