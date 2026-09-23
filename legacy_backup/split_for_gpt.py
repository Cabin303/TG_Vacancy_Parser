from pathlib import Path
import re
import tkinter as tk
from tkinter import filedialog


BASE_DIR = Path(__file__).parent
OUTPUT_DIR = None

POSTS_PER_FILE = 10



def choose_result_file():
    root = tk.Tk()
    root.withdraw()

    file_path = filedialog.askopenfilename(
        title="Выберите файл результатов Telegram",
        filetypes=[("Text files", "*.txt"), ("All files", "*")]
    )

    root.destroy()

    if not file_path:
        return None

    return Path(file_path)


def split_posts(text):
    posts = re.findall(
        r"={20,}\s*\nКАНАЛ:.*?(?=\n={20,}\s*\nКАНАЛ:|\Z)",
        text,
        flags=re.S
    )

    return [p.strip() for p in posts]


def save_batches(posts):
    global OUTPUT_DIR

    if OUTPUT_DIR is None:
        raise ValueError("Не задана папка результатов")

    OUTPUT_DIR.mkdir(exist_ok=True)

    for file in OUTPUT_DIR.glob("batch_*.md"):
        file.unlink()

    for i in range(0, len(posts), POSTS_PER_FILE):
        batch = posts[i:i + POSTS_PER_FILE]

        filename = OUTPUT_DIR / f"batch_{i // POSTS_PER_FILE + 1:03}.md"

        with filename.open("w", encoding="utf-8") as f:
            f.write("# Telegram vacancy batch\n\n")

            for post in batch:
                f.write(post)
                f.write("\n\n================================================================================\n\n")

        print(f"Создан: {filename.name}")


def main():
    source = choose_result_file()

    if source is None:
        return

    global OUTPUT_DIR
    OUTPUT_DIR = source.parent / "GPT_batches"

    print(f"Источник: {source.name}")

    text = source.read_text(encoding="utf-8")

    posts = split_posts(text)

    print(f"Найдено постов: {len(posts)}")

    save_batches(posts)

    print("Готово")


if __name__ == "__main__":
    main()