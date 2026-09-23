"""Splitter: разбиение результата парсера на батчи для GPT.

Логика перенесена из original split_for_gpt.py без изменений:
  * посты выделяются тем же регулярным выражением (блоки '====... КАНАЛ: ...');
  * выход — папка 'GPT_batches' рядом с исходным файлом;
  * файлы batch_NNN.md с заголовком '# Telegram vacancy batch',
    посты разделены строкой из '='.
Посты в батче: POSTS_PER_FILE (по умолчанию 10).
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

SEPARATOR = "=" * 80

POST_SPLIT_RE = re.compile(
    r"={20,}\s*\nКАНАЛ:.*?(?=\n={20,}\s*\nКАНАЛ:|\Z)",
    flags=re.S,
)


@dataclass
class SplitStats:
    source: Path
    output_dir: Path
    num_posts: int = 0
    num_files: int = 0


def split_posts(text: str) -> list[str]:
    posts = POST_SPLIT_RE.findall(text)
    return [p.strip() for p in posts]


def get_output_dir(source: Path) -> Path:
    return source.parent / "GPT_batches"


def run_split(
    source: Path,
    posts_per_file: int = 10,
    output_dir: Path | None = None,
    notify=None,
) -> SplitStats:
    """Читает source, бьёт на посты, пишет батчи. Возвращает статистику."""
    notify = notify or (lambda **_: None)

    if not source.exists():
        raise FileNotFoundError(f"Файл результатов не найден: {source}")

    if posts_per_file < 1:
        raise ValueError("Количество постов в файле должно быть >= 1")

    out_dir = Path(output_dir or get_output_dir(source))
    out_dir.mkdir(parents=True, exist_ok=True)

    for old in out_dir.glob("batch_*.md"):
        old.unlink()

    text = source.read_text(encoding="utf-8")
    posts = split_posts(text)
    log.info("Splitter: %s → %d постов", source.name, len(posts))

    notify(type="split_posts", source=source, num_posts=len(posts))

    files_written = 0
    for i in range(0, len(posts), posts_per_file):
        batch = posts[i:i + posts_per_file]
        filename = out_dir / f"batch_{i // posts_per_file + 1:03}.md"
        with filename.open("w", encoding="utf-8") as f:
            f.write("# Telegram vacancy batch\n\n")
            for post in batch:
                f.write(post)
                f.write(f"\n\n{SEPARATOR}\n\n")
        files_written += 1
        log.info("Создан: %s", filename.name)
        notify(type="batch_written", file=str(filename), batch_index=i // posts_per_file + 1)

    return SplitStats(
        source=Path(source),
        output_dir=out_dir,
        num_posts=len(posts),
        num_files=files_written,
    )