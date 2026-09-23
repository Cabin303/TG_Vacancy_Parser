"""Web-скрапинг публичного превью канала Telegram (telegram.me/s/<channel>).

Логика перенесена из оригинального main.py: тот же URL, те же заголовки,
та же обработка редиректов и HTML-структуры. Изменения:
  * запросы обёрнуты в исключения — ошибка одного канала не роняет весь запуск;
  * пост без даты/ссылки больше не вызывает NameError (раньше парсер падал);
  * отдача результатов в виде списка структур вместо прямой записи в файл
    (запись в файл делает parse.py — так проще тестировать и переиспользовать).
"""

import logging
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

BASE_URL = "https://telegram.me/s/{channel}"
USER_AGENT = "Mozilla/5.0"
REQUEST_TIMEOUT = 20

REDIRECT_STATUS_CODES = (301, 302, 303, 307, 308)


@dataclass
class FoundPost:
    channel: str
    message_id: str
    link: str
    post_date: str
    text: str


@dataclass
class ChannelStats:
    posts_checked: int = 0
    posts_skipped: int = 0
    posts_found: int = 0


def fetch_page(channel: str, timeout: int = REQUEST_TIMEOUT) -> requests.Response:
    """GET-запрос страницы канала. Кидает OSError/requests-исключение при сбое."""
    url = BASE_URL.format(channel=channel)
    log.info("Скачиваю %s ...", url)
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
        allow_redirects=False,
    )
    response.raise_for_status()
    return response


def is_redirect(response: requests.Response) -> bool:
    return response.status_code in REDIRECT_STATUS_CODES


def parse_channel_posts(
    html: str,
    channel: str,
    seen_posts: dict,
    normalized_keywords: list,
) -> tuple[list[FoundPost], ChannelStats]:
    """Разбирает HTML страницы канала.

    Возвращает (найденные посты, статистика). Посты, которые уже есть в
    seen_posts, пропускаются. В seen_posts НИЧЕГО не добавляется — это делает
    вызывающий код только для найденных постов (как в оригинале).
    """
    soup = BeautifulSoup(html, "lxml")
    wrappers = soup.find_all("div", class_="tgme_widget_message_wrap")

    stats = ChannelStats()
    found: list[FoundPost] = []

    for wrapper in wrappers:
        date = wrapper.find("a", class_="tgme_widget_message_date")
        message_id = "?"
        link = "-"
        post_date = "не указана"
        current_id = None

        if date and date.get("href"):
            href = date["href"]
            time_tag = date.find("time")
            if time_tag and time_tag.get("datetime"):
                post_date = time_tag["datetime"].split("T")[0]
            link = f"https://telegram.me{href}" if href.startswith("/") else href
            link = link.replace("https://t.me/", "https://telegram.me/")
            message_id = href.rstrip("/").split("/")[-1]

            try:
                current_id = int(message_id)
            except ValueError:
                current_id = None

            channel_seen = seen_posts.get(channel, [])
            if current_id is not None and str(current_id) in channel_seen:
                continue

        text_block = wrapper.find("div", class_="tgme_widget_message_text")
        if not text_block:
            stats.posts_skipped += 1
            continue

        original_text = text_block.get_text("\n", strip=True)
        full_text = "".join(original_text.lower().split())
        stats.posts_checked += 1

        if any(keyword in full_text for keyword in normalized_keywords):
            stats.posts_found += 1
            found.append(
                FoundPost(
                    channel=channel,
                    message_id=message_id,
                    link=link,
                    post_date=post_date,
                    text=text_block.get_text("\n", strip=True),
                )
            )

    return found, stats