"""Поисковые ключевые слова и их нормализация.

Список перенесён из оригинального main.py без изменений — поведение поиска
сохраняется 1:1. Нормализация: приведение к нижнему регистру и удаление всех
пробелов (как в исходном коде: "".join(keyword.lower().split())).
"""

KEYWORDS = [
    "second officer",
    "second off",
    "second mate",
    "2nd officer",
    "2nd off",
    "2nd mate",
    "2/o",
    "2/off",
    "2 off",
    "2off",
    "второй помощник",
    "второй помощник капитана",
    "второй помощник капитана судна",
    "third officer",
    "third off",
    "third mate",
    "3rd officer",
    "3rd off",
    "3rd mate",
    "3/o",
    "3/off",
    "3 off",
    "3off",
    "третий помощник",
    "третий помощник капитана",
    "третий помощник капитана судна",
    "oow",
    # Second Officer
    "2 officer",
    "2o",
    "2 officer dpo",
    "2nd officer dpo",
    "second officer dpo",
    "2 officer dp",
    "2nd officer dp",
    "second officer dp",
    # Third Officer
    "3 officer",
    "3o",
    "3 officer dpo",
    "3rd officer dpo",
    "third officer dpo",
    "3 officer dp",
    "3rd officer dp",
    "third officer dp",
    "3nd officer",  # встречается как опечатка
    # OOW
    "Вахтенный помощник капитана",
    "officer of the watch",
    "officer of watch",
    "watchkeeping officer",
    "officer in charge of a navigational watch",
    # Second Officer
    "2nd mate/oow",
    "second mate/oow",
    # Third Officer
    "3rd mate/oow",
    "third mate/oow",
    # OOW
    "navigational watch officer",
    "officer in charge of navigational watch",
    "officer in charge of the navigational watch",
    "officer in charge of a navigational watch",
    "officer in charge of navigational watch (oicnw)",
    "oicnw",
]

NORMALIZED_KEYWORDS = ["".join(k.lower().split()) for k in KEYWORDS]


def normalize_keyword(keyword: str) -> str:
    """Нормализация одной фразы: нижний регистр, без пробелов (как в оригинале)."""
    return "".join(keyword.lower().split())


def normalize_keywords(keywords) -> list:
    return [normalize_keyword(k) for k in keywords]