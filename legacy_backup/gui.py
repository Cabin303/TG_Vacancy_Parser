import tkinter as tk
from tkinter import filedialog
import subprocess
import sys
import threading
from pathlib import Path
import os
import shutil
from datetime import datetime


BASE_DIR = Path(__file__).parent
PARSER = BASE_DIR / "main.py"
RESULT_FILE = BASE_DIR / "telegram_found_posts.txt"

# Файл памяти просмотренных постов
SEEN_FILE = BASE_DIR / "seen_posts.json"

SETTINGS_FILE = BASE_DIR / "gui_settings.json"
SAVE_DIR = BASE_DIR


def load_settings():
    global SAVE_DIR
    try:
        import json
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                SAVE_DIR = Path(data.get("save_dir", BASE_DIR))
    except Exception:
        SAVE_DIR = BASE_DIR


def save_settings():
    import json
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump({"save_dir": str(SAVE_DIR)}, f, ensure_ascii=False, indent=4)


def choose_folder():
    global SAVE_DIR
    folder = filedialog.askdirectory(initialdir=str(SAVE_DIR))
    if folder:
        SAVE_DIR = Path(folder)
        save_settings()
        status_var.set(f"Папка: {SAVE_DIR.name}")

        folder_var.set(f"Сохранение: {SAVE_DIR}")


# Кнопка сброса памяти просмотренных постов
def reset_memory():
    if SEEN_FILE.exists():
        SEEN_FILE.write_text("{}", encoding="utf-8")
        status_var.set("Память сброшена. Следующий запуск покажет старые посты")
    else:
        status_var.set("Память уже пустая")


def run_parser():
    button_start.config(state="disabled")
    status_var.set("🔄 Запуск поиска...")
    progress_var.set("Канал: подготовка...")
    count_var.set("Найдено постов: 0")

    def worker():
        try:
            process = subprocess.Popen(
                [sys.executable, str(PARSER)],
                cwd=BASE_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )

            report_mode = False
            for line in process.stdout:
                line = line.strip()

                if line.startswith("КАНАЛ:"):
                    progress_var.set(line)

                elif "Постов показано:" in line:
                    count_var.set(line.replace("Постов показано:", "Найдено постов:"))

                elif "По каналам:" in line:
                    report_box.delete("1.0", tk.END)
                    report_box.insert(tk.END, "📊 Найдено постов по каналам:\n\n")
                    report_mode = True

                elif "report_mode" in locals() and report_mode:
                    if line and ":" in line and any(char.isdigit() for char in line):
                        report_box.insert(tk.END, line.replace("✅", "") + "\n")
                        report_box.see(tk.END)

            process.wait()

            source_file = BASE_DIR / RESULT_FILE.name

            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            target_file = SAVE_DIR / f"telegram_found_posts_{timestamp}.txt"

            if source_file.exists():
                shutil.copy2(source_file, target_file)
            else:
                target_file.write_text(
                    "Новых вакансий не найдено.\n\nПарсер завершил проверку каналов.",
                    encoding="utf-8"
                )

            status_var.set("Поиск завершён. Результат сохранён")

        except Exception as e:
            status_var.set(f"Ошибка: {e}")

        finally:
            button_start.config(state="normal")

    threading.Thread(target=worker, daemon=True).start()


def open_results():
    files = sorted(
        SAVE_DIR.glob("telegram_found_posts_*.txt"),
        key=lambda x: x.stat().st_mtime,
        reverse=True
    )

    if files:
        os.system(f'open "{files[0]}"')
        return

    old_file = SAVE_DIR / RESULT_FILE.name
    if old_file.exists():
        os.system(f'open "{old_file}"')
        return

    status_var.set(f"Результаты не найдены:\n{SAVE_DIR}")


# Окно
root = tk.Tk()
load_settings()
root.title("Telegram Vacancy Parser")
root.geometry("700x500")


title = tk.Label(
    root,
    text="Telegram Vacancy Parser",
    font=("Arial", 16)
)
title.pack(pady=10)


button_start = tk.Button(
    root,
    text="▶ Запустить поиск",
    command=run_parser,
    width=25
)
button_start.pack(pady=5)


button_open = tk.Button(
    root,
    text="📄 Открыть результаты",
    command=open_results,
    width=25
)
button_open.pack(pady=5)

button_folder = tk.Button(
    root,
    text="📂 Выбрать папку результатов",
    command=choose_folder,
    width=25
)
button_folder.pack(pady=5)

# Кнопка сброса памяти постов
button_reset = tk.Button(
    root,
    text="♻️ Сбросить память постов",
    command=reset_memory,
    width=25
)
button_reset.pack(pady=5)

folder_var = tk.StringVar()
folder_var.set(f"Сохранение: {SAVE_DIR}")

folder_label = tk.Label(
    root,
    textvariable=folder_var
)
folder_label.pack(pady=3)

progress_var = tk.StringVar()
progress_var.set("Канал: ожидание")

progress_label = tk.Label(
    root,
    textvariable=progress_var
)
progress_label.pack(pady=5)

count_var = tk.StringVar()
count_var.set("Найдено вакансий: 0")

count_label = tk.Label(
    root,
    textvariable=count_var,
    font=("Arial", 12)
)
count_label.pack(pady=5)


report_frame = tk.Frame(root)
report_frame.pack(pady=5)

report_box = tk.Text(
    report_frame,
    width=50,
    height=15
)
report_box.pack(side=tk.LEFT)

report_scroll = tk.Scrollbar(
    report_frame,
    command=report_box.yview
)
report_scroll.pack(side=tk.RIGHT, fill=tk.Y)

report_box.config(yscrollcommand=report_scroll.set)


status_var = tk.StringVar()
status_var.set("Ожидание запуска")

status = tk.Label(
    root,
    textvariable=status_var
)
status.pack(pady=5)


root.mainloop()