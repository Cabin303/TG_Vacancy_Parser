"""Оркестрация парсинга.

Сохраняет исходное поведение main.py:
  * стартовый результат-файл удаляется, затем последовательно дополняется
    найденными постами (по одному каналу за раз);
  * seen_posts наполняется только найденными постами;
  * файл состояния сохраняется в конце запуска (а теперь ещё и на отмене);
  * формат записи блока поста — 1:1 с оригиналом.

Изменения (диагностируемые и безопасные):
  * ошибка отдельного канала не роняет весь запуск — канал помечается,
    выполнение продолжается;
  * есть возможность отмены между каналами;
  * прогресс передаётся через callback вместо парсинга stdout GUI-ом;
  * источник списка поисковых фраз — vacancy_filters.json (фильтры из GUI),
    сама логика сопоставления не менялась.
"""

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.core.paths import RESULT_FILE, SEEN_FILE
from app.parser import channels as channel_store
from app.parser.keywords import normalize_keywords
from app.parser.scraper import (
    ChannelStats,
    fetch_page,
    is_redirect,
    parse_channel_posts,
)

log = logging.getLogger(__name__)

SEPARATOR = "=" * 80


def format_post_block(post) -> str:
    return (
        f"{SEPARATOR}\n"
        f"КАНАЛ: {post.channel}\n"
        f"ID: {post.message_id}\n"
        f"ССЫЛКА: {post.link}\n"
        f"ДАТА: {post.post_date}\n"
        f"{SEPARATOR}\n\n"
        f"{post.text}\n\n"
    )


@dataclass
class ParseStats:
    channels_checked: int = 0
    channels_ok: int = 0
    posts_checked: int = 0
    posts_found: int = 0
    posts_skipped: int = 0
    found_by_channel: dict = field(default_factory=dict)
    failed_channels: list = field(default_factory=list)
    cancelled: bool = False

    def to_report_lines(self) -> list[str]:
        lines = [
            f"Каналов проверено: {self.channels_checked}",
            f"Постов проверено: {self.posts_checked}",
            f"Постов показано: {self.posts_found}",
            f"Постов пропущено: {self.posts_checked - self.posts_found}",
        ]
        if self.failed_channels:
            lines.append(f"Каналов с ошибкой: {len(self.failed_channels)}")
            lines.append("Ошибки: " + ", ".join(self.failed_channels))
        if self.found_by_channel:
            lines.append("По каналам:")
            for ch, count in self.found_by_channel.items():
                lines.append(f"✅ {ch}: {count}")
        if self.cancelled:
            lines.append("⚠️ Запуск прерван пользователем (не полностью).")
        return lines


def run_parse(
    notify=None,
    stop_event: threading.Event | None = None,
    result_file: Path | None = None,
    seen_file: Path | None = None,
    channel_list: list[str] | None = None,
    keywords: list[str] | None = None,
) -> ParseStats:
    """Прогоняет парсер по каналам. Возвращает статистику выполнения.

    notify(event: dict) вызывается для прогресса; события для GUI описаны в
    ui/app_window.py. stop_event позволяет прервать запуск между каналами.
    keywords — поисковые фразы (по умолчанию: включённые фильтры из
    vacancy_filters.json). Нормализация и логика поиска не меняются.
    """
    notify = notify or (lambda **_: None)
    stop_event = stop_event or threading.Event()

    if keywords is None:
        from app.core import filters as filters_store

        keywords = filters_store.active_names(filters_store.load_filters())
    normalized_keywords = normalize_keywords(keywords)

    out = Path(result_file or RESULT_FILE)
    seen_path = Path(seen_file or SEEN_FILE)
    channels = list(channel_list) if channel_list is not None else channel_store.load_channels()

    if not channels:
        raise ValueError("Список каналов пуст — добавьте каналы в channels.txt")

    seen_posts: dict = {}
    if seen_path.exists():
        try:
            with seen_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                seen_posts = data
        except (OSError, ValueError) as e:
            log.warning("Не удалось прочитать %s: %s — начнём заново", seen_path, e)
            seen_posts = {}

    if out.exists():
        out.unlink()

    stats = ParseStats()

    try:
        with out.open("w", encoding="utf-8") as output:
            for channel in channels:
                if stop_event.is_set():
                    stats.cancelled = True
                    notify(type="log", level="warning", message="⚠️ Запуск прерван пользователем")
                    break

                stats.channels_checked += 1
                notify(type="channel_start", channel=channel)

                try:
                    response = fetch_page(channel)
                except Exception as e:  # noqa: BLE001 — осознанно ловим сеть/HTTP
                    stats.failed_channels.append(str(channel))
                    log.exception("Ошибка канала %s", channel)
                    notify(type="channel_error", channel=channel, error=str(e))
                    notify(type="log", level="error", message=f"❌ {channel}: {e}")
                    continue

                if is_redirect(response):
                    location = response.headers.get("Location", "-")
                    log.info("Канал %s: редирект %s", channel, location)
                    notify(type="channel_redirect", channel=channel, location=location)
                    notify(type="log", level="warning", message=f"⚠️ {channel}: редирект пропущен: {location}")
                    continue

                if response.status_code != 200:
                    log.info("Канал %s: HTTP %s", channel, response.status_code)
                    notify(type="channel_http_error", channel=channel, status=response.status_code)
                    notify(type="log", level="warning", message=f"⚠️ {channel}: HTTP {response.status_code}")
                    continue

                found_posts, channel_stats = parse_channel_posts(
                    response.text, channel, seen_posts, normalized_keywords
                )
                stats.channels_ok += 1
                notify(type="channel_page", channel=channel, posts_in_html=channel_stats.posts_checked)

                for post in found_posts:
                    seen_posts.setdefault(channel, []).append(str(post.message_id))
                    output.write(format_post_block(post))
                    output.flush()
                    notify(type="post_found", channel=channel, id=post.message_id, link=post.link, date=post.post_date)

                stats.posts_checked += channel_stats.posts_checked
                stats.posts_skipped += channel_stats.posts_skipped
                stats.posts_found += channel_stats.posts_found
                if channel_stats.posts_found:
                    stats.found_by_channel[channel] = stats.found_by_channel.get(channel, 0) + channel_stats.posts_found

                notify(type="channel_done", channel=channel, posts_found=channel_stats.posts_found)
    finally:
        try:
            with seen_path.open("w", encoding="utf-8") as f:
                json.dump(seen_posts, f, indent=4, ensure_ascii=False)
        except OSError as e:
            log.error("Не удалось сохранить %s: %s", seen_path, e)
            raise

    log.info("Парсинг завершён: %s", asdict(stats))
    return stats