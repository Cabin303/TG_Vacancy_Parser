#!/usr/bin/env python3
"""Совместимая точка входа: запускает единый GUI (Parser + Splitter).

Раньше здесь был отдельный GUI Parser-а (запускал main.py в subprocess).
Теперь всё объединено в app/ui/app_window.py.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())