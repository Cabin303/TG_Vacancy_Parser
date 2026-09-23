"""Единая точка входа приложения.

  без аргументов          — графический интерфейс
  --parse                 — только Parser (headless, печать статистики)
  --split <файл> [--posts N] — только Splitter на существующем результате
  --full                  — полный цикл (Parser → Splitter)

Путь к проекту не зависит от текущей рабочей директории.
"""

import argparse
import logging
import sys
from pathlib import Path

from app import runner
from app.core import connection as connection_core
from app.core import logging_setup


def _print_headless(stats, result_file: Path) -> None:
    for line in stats.to_report_lines():
        print(line)
    if result_file.exists():
        print(f"Результат: {result_file}")


def cmd_parse(args) -> int:
    pipeline = runner.Pipeline(connection_checker=connection_core.check_connection)
    try:
        stats = pipeline.parse()
    except runner.ConnectionBlockedError as e:
        print(f"Parser не запущен: {e}")
        return 1
    except Exception as e:
        print(f"ОШИБКА: {e}")
        return 1
    _print_headless(stats, pipeline.result_file)
    return 0


def cmd_split(args) -> int:
    pipeline = runner.Pipeline()
    source = Path(args.split)
    try:
        split_stats = pipeline.split(source=source, posts_per_file=args.posts)
    except Exception as e:
        print(f"ОШИБКА: {e}")
        return 1
    print(f"Источник: {source}")
    print(f"Найдено постов: {split_stats.num_posts}")
    print(f"Батчей создано: {split_stats.num_files}")
    print(f"Папка: {split_stats.output_dir}")
    return 0


def cmd_full(args) -> int:
    pipeline = runner.Pipeline(connection_checker=connection_core.check_connection)
    try:
        stage, stats, split_stats = pipeline.run_all()
    except runner.ConnectionBlockedError as e:
        print(f"Parser не запущен: {e}")
        return 1
    except Exception as e:
        print(f"ОШИБКА: {e}")
        return 1
    _print_headless(stats, pipeline.result_file)
    print()
    if split_stats:
        print(f"Батчей создано: {split_stats.num_files}")
        print(f"Папка: {split_stats.output_dir}")
    return 0


def main(argv=None) -> int:
    logging_setup.setup_logging()

    parser = argparse.ArgumentParser(
        prog="tg_vacancy_parser",
        description="Telegram Vacancy Parser + Splitter (единое приложение)",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--parse", action="store_true", help="только парсинг (без GUI)")
    group.add_argument("--split", metavar="ФАЙЛ", help="разбить существующий результат (без GUI)")
    group.add_argument("--full", action="store_true", help="полный цикл: парсинг + разбиение (без GUI)")
    parser.add_argument("--posts", type=int, default=None, help="постов в файле (для --split/--full)")
    args = parser.parse_args(argv)

    if args.parse:
        return cmd_parse(args)
    if args.split:
        return cmd_split(args)
    if args.full:
        return cmd_full(args)

    from app.ui.app_window import AppWindow

    window = AppWindow()
    window.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())