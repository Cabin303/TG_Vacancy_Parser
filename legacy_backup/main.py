# Привет Андрей
import requests
from bs4 import BeautifulSoup
import json
from pathlib import Path

print("RUNNING SIMPLE PARSER")
# GUI будет вынесен отдельно, поэтому логику парсера здесь не менять.

channels_checked = 0
posts_checked = 0
posts_found = 0
posts_skipped = 0
found_by_channel = {}

search_keywords = [
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
    'Вахтенный помощник капитана',
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

normalized_keywords = ["".join(keyword.lower().split()) for keyword in search_keywords]

with open("channels.txt", "r", encoding="utf-8") as f:
    channels = [line.strip() for line in f if line.strip()]

state_file = Path("seen_posts.json")
output_file = Path("telegram_found_posts.txt")

if output_file.exists():
    output_file.unlink()

if state_file.exists():
    with state_file.open("r", encoding="utf-8") as f:
        seen_posts = json.load(f)
else:
    seen_posts = {}

for channel in channels:
    channels_checked += 1

    # url = f"https://t.me/s/{channel}"
    url = f"https://telegram.me/s/{channel}"
    print(f"\n{'=' * 50}")
    print(f"КАНАЛ: {channel}")
    print(f"Скачиваю {url}...")

    response = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20,
        allow_redirects=False,
    )

    if response.status_code in (301, 302, 303, 307, 308):
        print(f"Редирект пропущен: {response.headers.get('Location')}")
        continue

    if response.status_code != 200:
        print(f"Не удалось получить страницу. HTTP: {response.status_code}")
        continue

    soup = BeautifulSoup(response.text, "lxml")

    wrappers = soup.find_all("div", class_="tgme_widget_message_wrap")
    print(f"Найдено сообщений в HTML: {len(wrappers)}")

    max_id = 0

    for wrapper in wrappers:
        date = wrapper.find("a", class_="tgme_widget_message_date")
        message_id = "?"
        link = "-"
        post_date = "не указана"

        if date and date.get("href"):
            href = date["href"]
            time_tag = date.find("time")
            if time_tag and time_tag.get("datetime"):
                post_date = time_tag["datetime"].split("T")[0]
            link = f"https://telegram.me{href}" if href.startswith("/") else href
            link = link.replace("https://t.me/", "https://telegram.me/")
            message_id = href.rstrip("/").split("/")[-1]

            current_id = int(message_id)

            channel_seen = seen_posts.get(channel, [])
            if str(current_id) in channel_seen:
                continue

            if current_id > max_id:
                max_id = current_id

        text_block = wrapper.find("div", class_="tgme_widget_message_text")
        if not text_block:
            posts_skipped += 1
            continue

        original_text = text_block.get_text("\n", strip=True)
        full_text = "".join(original_text.lower().split())
        posts_checked += 1

        if any(keyword in full_text for keyword in normalized_keywords):
            if channel not in seen_posts:
                seen_posts[channel] = []

            seen_posts[channel].append(str(current_id))

            posts_found += 1
            found_by_channel[channel] = found_by_channel.get(channel, 0) + 1

            with output_file.open("a", encoding="utf-8") as out:
                out.write("=" * 80 + "\n")
                out.write(f"КАНАЛ: {channel}\n")
                out.write(f"ID: {message_id}\n")
                out.write(f"ССЫЛКА: {link}\n")
                out.write(f"ДАТА: {post_date}\n")
                out.write("=" * 80 + "\n\n")
                out.write(text_block.get_text("\n", strip=True))
                out.write("\n\n")

            print("=" * 50)
            print(f"КАНАЛ: {channel}")
            print(f"ID: {message_id}")
            print(f"ССЫЛКА: {link}")
            print(f"ДАТА: {post_date}\n")
            print(text_block.get_text("\n", strip=True))
            print("=" * 50)

with state_file.open("w", encoding="utf-8") as f:
    json.dump(seen_posts, f, indent=4, ensure_ascii=False)

print("\n" + "=" * 50)
print("📊 СТАТИСТИКА ПАРСЕРА")
print("=" * 50)
print(f"Каналов проверено: {channels_checked}")
print(f"Постов проверено: {posts_checked}")
print(f"Постов показано: {posts_found}")
print(f"Постов пропущено: {posts_checked - posts_found}")

if found_by_channel:
    print("\nПо каналам:")
    for ch, count in found_by_channel.items():
        print(f"✅ {ch}: {count}")

print("=" * 50)
