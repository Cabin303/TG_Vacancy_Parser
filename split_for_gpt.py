#!/usr/bin/env python3
"""Точка входа Splitter.

  python split_for_gpt.py                  — открывает единый GUI
  python split_for_gpt.py <файл.txt>       — сразу разбивает указанный файл

Разбиение выполняется общим движком app/splitter/split.py.
"""

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from app.main import main  # noqa: E402

if __name__ == "__main__":
    argv = sys.argv[1:]
    if argv and Path(argv[0]).exists():
        sys.exit(main(["--split", str(Path(argv[0]).resolve())]))
    sys.exit(main())