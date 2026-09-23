"""Контроллер единого workflow: Check → Parse → (Split) → DONE.

Правила ТЗ:
  * перед Parser выполняется проверка соединения (интернет + Telegram);
    если соединения нет — Parser не запускается (ConnectionBlockedError);
  * Parser ERROR → Splitter не запускается (исключение/ни один канал не обработан);
  * результат Parser сохраняется всегда, поэтому Splitter можно запустить
    повторно на последнем результате из-под GUI/CLI;
  * файл результата и выход Splitter живут в выбранной папке сохранения (save_dir).
"""

import logging
from pathlib import Path

from app.core import connection as connection_core
from app.core import paths, settings
from app.parser.parse import ParseStats, run_parse
from app.splitter.split import SplitStats, run_split

log = logging.getLogger(__name__)


class PipelineError(RuntimeError):
    """Критическая ошибка этапа, после которой следующий этап не запускается."""


class ConnectionBlockedError(PipelineError):
    """Соединения нет — Parser запускать нельзя."""

    def __init__(self, message: str, state=None):
        super().__init__(message)
        self.state = state


class Pipeline:
    def __init__(self, current_settings: dict | None = None, notify=None,
                 result_file: Path | None = None, seen_file: Path | None = None,
                 channels: list[str] | None = None, keywords: list[str] | None = None,
                 connection_checker=None):
        self.settings = current_settings or settings.load_settings()
        self.notify = notify or (lambda **_: None)
        save_dir = self.settings.get("save_dir", str(paths.DEFAULT_SAVE_DIR))
        self.result_file = Path(result_file or paths.result_file_for(save_dir))
        self.seen_file = Path(seen_file or paths.SEEN_FILE)
        self.channels = channels
        self.keywords = keywords
        self.connection_checker = connection_checker

    def _require_connection(self):
        state = self.connection_checker()
        if not state.usable_for_parser():
            if state.internet is False:
                raise ConnectionBlockedError("Интернет отсутствует. Проверьте подключение.", state)
            raise ConnectionBlockedError("Интернет доступен, но Telegram недоступен.", state)
        return state

    def parse(self, stop_event=None) -> ParseStats:
        if self.connection_checker is not None:
            self.notify(type="stage", stage="check")
            state = self._require_connection()
            self.notify(type="connection", state=state)
        self.notify(type="stage", stage="parse")
        stats = run_parse(
            notify=self.notify,
            stop_event=stop_event,
            result_file=self.result_file,
            seen_file=self.seen_file,
            channel_list=self.channels,
            keywords=self.keywords,
        )
        if (not stats.cancelled
                and stats.channels_checked > 0
                and stats.channels_ok == 0):
            raise PipelineError(
                "Парсер не смог обработать ни один канал — результат не создан. "
                "Проверьте подключение и доступность каналов."
            )
        return stats

    def split(self, source: Path | None = None, posts_per_file: int | None = None,
              output_dir: Path | None = None) -> SplitStats:
        source = Path(source or self.result_file)
        per_file = posts_per_file or int(self.settings.get("posts_per_file", 10))
        return run_split(source, posts_per_file=per_file, output_dir=output_dir, notify=self.notify)

    def run_all(self, stop_event=None) -> tuple[str, ParseStats | None, SplitStats | None]:
        """Выполняет полный цикл. Бросает PipelineError при критической ошибке."""
        self.notify(type="stage", stage="check")
        self.notify(type="stage", stage="parse")
        stats = self.parse(stop_event)

        if stats.cancelled:
            self.notify(type="log", level="warning", message="Отмена: Splitter не запускается.")
            return "cancelled", stats, None

        if self.settings.get("auto_split", True):
            self.notify(type="stage", stage="split")
            split_stats = self.split(posts_per_file=int(self.settings.get("posts_per_file", 10)))
            return "done", stats, split_stats

        return "partial", stats, None