"""Единый GUI: Connection Monitor + Vacancy Filters + Save Dir + Parser + Splitter.

Структура (ТЗ §17/§22):
    Индикатор соединения → Вакансии → Каналы → Папка сохранения →
    Настройки → Workflow → Лог.

Все обновления UI происходят только из главного потока через очередь
событий — рабочая логика выполняется в фоновом потоке и никогда не трогает
tkinter напрямую. Проверки соединения идут асинхронно (ConnectionMonitor).
"""

import logging
import os
import queue
import shutil
import threading
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

from app.core import connection as connection_core
from app.core import filters as filters_store
from app.core import paths, settings as settings_store
from app.parser import channels as channel_store
from app.runner import ConnectionBlockedError, Pipeline, PipelineError

log = logging.getLogger(__name__)


class AppWindow:
    def __init__(self):
        self.settings = settings_store.load_settings()
        self.events: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker = None
        self.total_found = 0
        self._save_dir = Path(self.settings.get("save_dir", paths.DEFAULT_SAVE_DIR))
        self._conn_monitor = connection_core.ConnectionMonitor(
            interval=connection_core.DEFAULT_INTERVAL
        )
        self._conn_state = connection_core.ConnectionState()

        self.root = tk.Tk()
        self.root.title("Telegram Vacancy Parser + Splitter")

        self._build_widgets()
        self._apply_optimal_size()
        self._load_channels_to_list()
        self._load_filters_to_list()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(120, self._poll_events)
        self._refresh_connection()

    def _apply_optimal_size(self):
        self.root.update()
        req_w = max(880, self.root.winfo_reqwidth())
        req_h = max(760, self.root.winfo_reqheight())
        width = min(req_w, self.root.winfo_screenwidth() - 60)
        height = min(req_h, self.root.winfo_screenheight() - 80)
        self.root.minsize(width=880, height=760)
        self.root.geometry(f"{width}x{height}")

    # ------------------------------------------------------------- widgets
    def _build_widgets(self):
        pad = {"padx": 8, "pady": 3}

        header = tk.Label(self.root, text="Telegram Vacancy Parser + Splitter", font=("Arial", 15))
        header.pack(pady=(8, 2))

        # --- Индикатор соединения (всегда виден) -----------------------
        self.conn_var = tk.StringVar(value=self._conn_state.label)
        self.conn_label = tk.Label(
            self.root,
            textvariable=self.conn_var,
            fg=self._conn_state.color,
            font=("Arial", 11, "bold"),
            anchor="w",
        )
        self.conn_label.pack(fill=tk.X, **pad)

        # --- Вакансии ---------------------------------------------------
        vac_frame = tk.LabelFrame(self.root, text="Вакансии", padx=8, pady=5)
        vac_frame.pack(fill=tk.X, **pad)

        self.filters_list = tk.Listbox(vac_frame, height=6, exportselection=False)
        self.filters_list.pack(side=tk.LEFT, fill=tk.X, expand=True)
        vac_scroll = tk.Scrollbar(vac_frame, command=self.filters_list.yview)
        vac_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.filters_list.config(yscrollcommand=vac_scroll.set)
        self.filters_list.bind("<Double-1>", lambda e: self._toggle_filter())

        vac_btns = tk.Frame(vac_frame)
        vac_btns.pack(side=tk.LEFT, padx=(8, 0))
        tk.Button(vac_btns, text="Добавить", width=12, command=self._add_filter).pack(pady=1)
        tk.Button(vac_btns, text="Изменить", width=12, command=self._edit_filter).pack(pady=1)
        tk.Button(vac_btns, text="Удалить", width=12, command=self._remove_filter).pack(pady=1)
        tk.Button(vac_btns, text="Вкл/Выкл", width=12, command=self._toggle_filter).pack(pady=1)

        # --- Каналы -----------------------------------------------------
        ch_frame = tk.LabelFrame(self.root, text="Каналы (channels.txt)", padx=8, pady=5)
        ch_frame.pack(fill=tk.X, **pad)

        self.channel_list = tk.Listbox(ch_frame, height=5, exportselection=False)
        self.channel_list.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ch_scroll = tk.Scrollbar(ch_frame, command=self.channel_list.yview)
        ch_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.channel_list.config(yscrollcommand=ch_scroll.set)

        self.channel_entry = tk.Entry(ch_frame)
        self.channel_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))
        self.channel_entry.insert(0, "имя_канала (без @ и https)")
        self.channel_entry.bind("<Return>", lambda e: self._add_channel())

        btn_add = tk.Button(ch_frame, text="➕ Добавить", command=self._add_channel)
        btn_add.pack(side=tk.LEFT, padx=4)
        btn_del = tk.Button(ch_frame, text="➖ Удалить", command=self._remove_channel)
        btn_del.pack(side=tk.LEFT, padx=4)
        btn_sv = tk.Button(ch_frame, text="💾 Сохранить", command=self._save_channels)
        btn_sv.pack(side=tk.LEFT, padx=4)

        # --- Папка сохранения ------------------------------------------
        sd_frame = tk.LabelFrame(self.root, text="Папка сохранения", padx=8, pady=5)
        sd_frame.pack(fill=tk.X, **pad)

        self.save_dir_var = tk.StringVar(value=str(self._save_dir))
        tk.Entry(sd_frame, textvariable=self.save_dir_var, state="readonly").pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )
        tk.Button(sd_frame, text="Выбрать папку", command=self._choose_save_dir).pack(
            side=tk.LEFT, padx=(8, 4)
        )
        tk.Button(sd_frame, text="Сбросить", command=self._reset_save_dir).pack(side=tk.LEFT)

        # --- Настройки --------------------------------------------------
        set_frame = tk.LabelFrame(self.root, text="Настройки", padx=8, pady=5)
        set_frame.pack(fill=tk.X, **pad)

        self.auto_split_var = tk.BooleanVar(value=bool(self.settings.get("auto_split", True)))
        tk.Checkbutton(set_frame, text="Автоматически запускать Splitter после парсинга",
                       variable=self.auto_split_var).pack(side=tk.LEFT)

        tk.Label(set_frame, text="Постов в файле:").pack(side=tk.LEFT, padx=(12, 4))
        self.posts_var = tk.IntVar(value=int(self.settings.get("posts_per_file", 10)))
        tk.Spinbox(set_frame, from_=1, to=200, textvariable=self.posts_var, width=5).pack(side=tk.LEFT)

        tk.Button(set_frame, text="♻️ Сбросить память постов", command=self._reset_memory).pack(side=tk.LEFT, padx=(12, 4))
        tk.Button(set_frame, text="📄 Открыть результат", command=self._open_results).pack(side=tk.LEFT, padx=4)

        # --- Workflow ---------------------------------------------------
        run_frame = tk.LabelFrame(self.root, text="Workflow", padx=8, pady=5)
        run_frame.pack(fill=tk.X, **pad)

        self.btn_full = tk.Button(run_frame, text="▶ Запустить всё", command=lambda: self._run("full"), width=18)
        self.btn_full.pack(side=tk.LEFT, padx=3)
        self.btn_parse = tk.Button(run_frame, text="Парсинг", command=lambda: self._run("parse"), width=12)
        self.btn_parse.pack(side=tk.LEFT, padx=3)
        self.btn_split = tk.Button(run_frame, text="✂ Разбить результат", command=lambda: self._run("split"), width=16)
        self.btn_split.pack(side=tk.LEFT, padx=3)
        self.btn_split_file = tk.Button(run_frame, text="✂ Другой файл…", command=self._run_split_file, width=12)
        self.btn_split_file.pack(side=tk.LEFT, padx=3)
        self.btn_cancel = tk.Button(run_frame, text="⛔ Отмена", command=self._cancel, state=tk.DISABLED, width=9)
        self.btn_cancel.pack(side=tk.RIGHT, padx=3)

        # --- Состояние --------------------------------------------------
        self.progress_var = tk.StringVar(value="Канал: ожидание")
        self.progress_var.trace_add("write", self._truncate_progress)
        tk.Label(self.root, textvariable=self.progress_var, anchor="w").pack(fill=tk.X, **pad)

        self.count_var = tk.StringVar(value="Найдено постов: 0")
        tk.Label(self.root, textvariable=self.count_var, font=("Arial", 12), anchor="w").pack(fill=tk.X, **pad)

        self.status_var = tk.StringVar(value="Ожидание запуска")
        tk.Label(self.root, textvariable=self.status_var, fg="#1a5fb4", anchor="w").pack(fill=tk.X, **pad)

        # --- Лог --------------------------------------------------------
        log_frame = tk.LabelFrame(self.root, text="Лог", padx=8, pady=5)
        log_frame.pack(fill=tk.BOTH, expand=True, **pad)
        self.log_box = tk.Text(log_frame, height=10, wrap=tk.WORD)
        self.log_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll = tk.Scrollbar(log_frame, command=self.log_box.yview)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_box.config(yscrollcommand=log_scroll.set)

        self._log("info", "Приложение запущено. Выберите вакансии и каналы, затем «Запустить всё».")

    # ------------------------------------------------- connection monitor
    def _refresh_connection(self):
        """Запускает проверку соединения в фоне (не блокирует GUI)."""
        self._conn_monitor.run_once(
            on_result=lambda state: self.events.put({"type": "connection", "state": state})
        )

    def _conn_checker(self):
        """Проверка перед запуском Parser: обновляет индикатор и возвращает состояние."""
        state = connection_core.check_connection(timeout=connection_core.DEFAULT_TIMEOUT)
        self.events.put({"type": "connection", "state": state})
        return state

    # ---------------------------------------------------- channels (UI)
    def _load_channels_to_list(self):
        self.channel_list.delete(0, tk.END)
        for ch in channel_store.load_channels():
            self.channel_list.insert(tk.END, ch)

    def _add_channel(self):
        name = self.channel_entry.get().strip().lstrip("@").strip()
        if name and name not in self.channel_list.get(0, tk.END):
            self.channel_list.insert(tk.END, name)
            self.channel_entry.delete(0, tk.END)

    def _remove_channel(self):
        selection = list(self.channel_list.curselection())
        for index in reversed(selection):
            self.channel_list.delete(index)

    def _save_channels(self):
        channels = list(self.channel_list.get(0, tk.END))
        try:
            channel_store.save_channels(channels)
        except OSError as e:
            self._log("error", f"Не удалось сохранить channels.txt: {e}")
            return
        self._log("ok", f"Список каналов сохранён: {len(channels)} шт. ({paths.CHANNELS_FILE.name})")

    # ------------------------------------------------- vacancy filters
    def _load_filters_to_list(self):
        self.filters = filters_store.load_filters()
        self._render_filters()

    def _render_filters(self):
        self.filters_list.delete(0, tk.END)
        for entry in self.filters:
            mark = "☑" if entry.get("enabled") else "☐"
            self.filters_list.insert(tk.END, f"{mark} {entry['name']}")

    def _selected_filter_index(self):
        selection = self.filters_list.curselection()
        return selection[0] if selection else None

    def _persist_filters(self):
        try:
            filters_store.save_filters(self.filters)
        except OSError as e:
            self._log("error", f"Не удалось сохранить {paths.FILTERS_FILE.name}: {e}")
            return
        self._render_filters()

    def _add_filter(self):
        name = simpledialog.askstring("Добавить вакансию", "Название вакансии:", parent=self.root)
        if name is None or not name.strip():
            return
        self.filters = filters_store.add_filter(self.filters, name)
        self._persist_filters()
        self._log("ok", f"Добавлена фраза: {name.strip()}")

    def _edit_filter(self):
        index = self._selected_filter_index()
        if index is None:
            self._log("warning", "Выберите фразу в списке для изменения.")
            return
        current = self.filters[index]
        name = simpledialog.askstring(
            "Изменить вакансию",
            "Название вакансии:",
            initialvalue=current["name"],
            parent=self.root,
        )
        if name is None or not name.strip():
            return
        self.filters = filters_store.update_filter(self.filters, index, name)
        self._persist_filters()
        self._log("ok", f"Фраза изменена: {current['name']} → {name.strip()}")

    def _remove_filter(self):
        index = self._selected_filter_index()
        if index is None:
            self._log("warning", "Выберите фразу в списке для удаления.")
            return
        current = self.filters[index]
        if not messagebox.askyesno(
            "Удалить", f"Удалить фразу «{current['name']}»?", parent=self.root
        ):
            return
        self.filters = filters_store.remove_filter(self.filters, index)
        self._persist_filters()
        self._log("ok", f"Фраза удалена: {current['name']}")

    def _toggle_filter(self, event=None):
        index = self._selected_filter_index()
        if index is None:
            self._log("warning", "Выберите фразу для включения/отключения.")
            return
        self.filters = filters_store.toggle_filter(self.filters, index)
        self._persist_filters()
        state = "включена" if self.filters[index]["enabled"] else "отключена"
        self._log("info", f"Фраза {state}: {self.filters[index]['name']}")

    # ------------------------------------------------------- save dir
    def _choose_save_dir(self):
        folder = filedialog.askdirectory(
            initialdir=str(self._save_dir), title="Выберите папку сохранения результатов"
        )
        if not folder:
            return
        self._set_save_dir(Path(folder))

    def _reset_save_dir(self):
        if not messagebox.askyesno(
            "Сброс папки",
            "Вернуть стандартную папку сохранения?",
            parent=self.root,
        ):
            return
        self._set_save_dir(Path(paths.DEFAULT_SAVE_DIR))

    def _set_save_dir(self, folder: Path):
        self._save_dir = folder
        self.settings["save_dir"] = str(folder)
        self.save_dir_var.set(str(folder))
        self._persist_settings()
        ok, message = paths.save_dir_status(folder)
        if not ok:
            self._log("error", message)
            messagebox.showwarning("Папка сохранения", message, parent=self.root)
            return
        self._log("ok", f"Папка сохранения: {folder}")

    # ------------------------------------------------------- settings
    def _reset_memory(self):
        seen = paths.SEEN_FILE
        try:
            if seen.exists():
                seen.write_text("{}", encoding="utf-8")
                self._log("ok", "Память просмотренных постов сброшена.")
            else:
                self._log("info", "Память и так пустая.")
        except OSError as e:
            self._log("error", f"Не удалось сбросить память: {e}")

    def _open_results(self):
        files = sorted(
            self._save_dir.glob("telegram_found_posts*.txt"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        target = files[0] if files else None
        if target is None and paths.result_file_for(self._save_dir).exists():
            target = paths.result_file_for(self._save_dir)
        if target:
            os.system(f'open "{target}"')
        else:
            self._log("warning", "Результаты ещё не найдены.")

    def _persist_settings(self):
        self.settings["posts_per_file"] = max(1, int(self.posts_var.get()))
        self.settings["auto_split"] = bool(self.auto_split_var.get())
        try:
            settings_store.save_settings(self.settings)
        except OSError as e:
            self._log("error", f"Не удалось сохранить настройки: {e}")

    def _on_close(self):
        self._persist_settings()
        self.root.destroy()

    # -------------------------------------------------------- execution
    def _set_busy(self, busy: bool):
        state = tk.DISABLED if busy else tk.NORMAL
        for widget in (self.btn_full, self.btn_parse, self.btn_split, self.btn_split_file):
            widget.config(state=state)
        self.btn_cancel.config(state=tk.NORMAL if busy else tk.DISABLED)

    def _notify(self, **kwargs):
        self.events.put(kwargs)

    def _run(self, mode: str):
        if self.worker and self.worker.is_alive():
            return
        self._persist_settings()
        self.total_found = 0
        self.count_var.set("Найдено постов: 0")
        self.stop_event.clear()
        self._set_busy(True)
        self._log("info", f"{'Запуск полного цикла' if mode == 'full' else 'Запуск'}...")
        self.worker = threading.Thread(target=self._worker, args=(mode,), daemon=True)
        self.worker.start()

    def _run_split_file(self):
        file = filedialog.askopenfilename(
            title="Выберите файл результатов Telegram",
            filetypes=[("Text files", "*.txt"), ("All files", "*")],
        )
        if not file:
            return
        self._run_source(Path(file))

    def _run_source(self, source: Path):
        pipeline = Pipeline(self.settings, notify=self._notify)
        try:
            stats = pipeline.split(source=source)
        except Exception as e:  # noqa: BLE001
            log.exception("Splitter: ошибка")
            self.status_var.set("Ошибка Splitter")
            self._log("error", f"Splitter: {e}")
            return
        self.status_var.set("Разбиение завершено")
        self._log("ok", f"Готово: постов {stats.num_posts}, файлов {stats.num_files} в {stats.output_dir}")

    def _worker(self, mode: str):
        checker = self._conn_checker if mode in ("full", "parse") else None
        pipeline = Pipeline(self.settings, notify=self._notify, connection_checker=checker)
        try:
            if mode in ("full", "parse"):
                ok, message = paths.save_dir_status(self._save_dir)
                if not ok:
                    self.events.put({"type": "save_dir_error", "message": message})
                    return

            if mode == "full":
                stage, stats, split_stats = pipeline.run_all(stop_event=self.stop_event)
                if stage in ("done", "partial"):
                    self._archive_result()
                self.events.put({"type": "stage_result", "stage": stage, "parse": stats, "split": split_stats})
            elif mode == "parse":
                stats = pipeline.parse(stop_event=self.stop_event)
                if not stats.cancelled:
                    self._archive_result()
                self.events.put({"type": "parse_result", "stats": stats})
            else:  # split — последний результат из папки сохранения
                try:
                    split_stats = pipeline.split(source=pipeline.result_file)
                    self.events.put({"type": "split_result", "stats": split_stats})
                except (FileNotFoundError, PipelineError) as e:
                    self.events.put({"type": "split_error", "message": str(e)})
        except ConnectionBlockedError as e:
            log.warning("Соединение недоступно: %s", e)
            self.events.put({"type": "connection_blocked", "message": str(e)})
        except PipelineError as e:
            log.warning("PipelineError: %s", e)
            self.events.put({"type": "pipeline_error", "message": str(e)})
        except Exception as e:  # noqa: BLE001
            log.exception("Фатальная ошибка worker")
            self.events.put({"type": "fatal_error", "message": str(e)})
        finally:
            self.events.put({"type": "busy_reset"})

    def _archive_result(self):
        source = paths.result_file_for(self._save_dir)
        if not source.exists():
            return
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        target = self._save_dir / f"telegram_found_posts_{timestamp}.txt"
        try:
            shutil.copy2(source, target)
            self.events.put({"type": "log", "level": "ok", "message": f"Архив результата: {target}"})
        except OSError as e:
            log.error("Не удалось скопировать результат: %s", e)
            self.events.put({"type": "log", "level": "error", "message": f"Архив результата: {e}"})

    def _cancel(self):
        self.stop_event.set()
        self.status_var.set("Отмена...")
        self._log("warning", "Отмена запрошена (завершение текущего канала)...")

    # ------------------------------------------------------- event pump
    def _poll_events(self):
        try:
            while True:
                ev = self.events.get_nowait()
                self._handle_event(ev)
        except queue.Empty:
            pass
        if self._conn_monitor.due():
            self._refresh_connection()
        self.root.after(120, self._poll_events)

    def _handle_event(self, ev):
        t = ev.get("type")

        if t == "log":
            self._log(ev.get("level", "info"), ev.get("message", ""))
        elif t == "connection":
            state = ev.get("state")
            self._conn_state = state
            self.conn_var.set(state.label)
            self.conn_label.config(fg=state.color)
        elif t == "stage":
            stage = ev.get("stage")
            if stage == "check":
                self.status_var.set("Проверка соединения...")
            elif stage == "parse":
                self.status_var.set("Этап: Parser → результат")
            else:
                self.status_var.set("Этап: Splitter → части")
        elif t == "stage_result":
            stage = ev.get("stage")
            if stage == "done":
                self.status_var.set("Полный цикл завершён: результат разбит")
                self._log("ok", "Полный цикл завершён: Parser → Splitter.")
            elif stage == "partial":
                self.status_var.set("Парсинг завершён (авто-разбиение отключено)")
            elif stage == "cancelled":
                self.status_var.set("Запуск прерван (результат частично сохранён)")
        elif t == "parse_result":
            stats = ev.get("stats")
            self.status_var.set("Поиск завершён. Результат сохранён")
            self._log("report", "\n".join(stats.to_report_lines()))
        elif t == "split_result":
            stats = ev.get("stats")
            self.status_var.set("Разбиение завершено")
            self._log("ok", f"Постов: {stats.num_posts}, файлов: {stats.num_files}, папка: {stats.output_dir}")
        elif t == "split_error":
            self._log("error", f"Splitter: {ev['message']}")
        elif t == "connection_blocked":
            self.status_var.set("Parser не запущен: нет соединения")
            self._log("error", f"Соединение: {ev['message']}")
            messagebox.showwarning("Соединение", ev["message"], parent=self.root)
        elif t == "save_dir_error":
            self.status_var.set("Папка сохранения недоступна")
            self._log("error", ev["message"])
            messagebox.showwarning("Папка сохранения", ev["message"], parent=self.root)
        elif t == "pipeline_error":
            self.status_var.set("Ошибка Parser — Splitter не запускается")
            self._log("error", f"Parser: {ev['message']}")
        elif t == "fatal_error":
            self.status_var.set("Критическая ошибка")
            self._log("error", f"{ev['message']}")
        elif t == "busy_reset":
            self._set_busy(False)

        elif t == "channel_start":
            self.progress_var.set(f"Канал: {ev.get('channel')}")
            self.status_var.set("Парсинг...")
        elif t == "channel_done":
            posts = ev.get("posts_found", 0)
            self.total_found += posts
            self.count_var.set(f"Найдено постов: {self.total_found}")
            if posts:
                self._log("post", f"✅ {ev['channel']}: {posts}")
        elif t == "post_found":
            self._log("post", f"  ➤ {ev['channel']} id={ev['id']} {ev['date']}")
        elif t == "channel_error":
            self._log("error", f"❌ {ev['channel']}: {ev['error']}")
        elif t == "channel_redirect":
            self._log("warning", f"⚠️ {ev['channel']}: редирект пропущен: {ev['location']}")
        elif t == "channel_http_error":
            self._log("warning", f"⚠️ {ev['channel']}: HTTP {ev['status']}")
        elif t == "channel_page":
            pass
        elif t == "split_posts":
            self.status_var.set(f"Splitter: найдено постов {ev.get('num_posts')}")
        elif t == "batch_written":
            self._log("info", f"Создан: {Path(ev.get('file', '')).name}")

    def _log(self, level: str, message: str):
        if not message:
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{stamp}] {message}"
        self.log_box.insert(tk.END, line + "\n")
        self.log_box.see(tk.END)

    def _truncate_progress(self, *_):
        value = self.progress_var.get()
        if len(value) > 120:
            self.progress_var.set(value[:117] + "...")

    # -------------------------------------------------------------- run
    def run(self):
        self.root.mainloop()