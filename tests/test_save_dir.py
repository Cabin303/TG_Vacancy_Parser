import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.test_parser import FakeResponse, page_with_posts

from app.core import paths, settings as settings_store
from app.parser import parse as parse_mod
from app.parser.scraper import FoundPost
from app.runner import Pipeline


class SettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="settings_test_"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.dir = self.tmp / f"t_{self._testMethodName}"
        self.dir.mkdir(exist_ok=True)
        self.settings_file = self.dir / "gui_settings.json"

    def test_defaults_when_file_missing(self):
        with mock.patch.object(paths, "SETTINGS_FILE", self.settings_file):
            loaded = settings_store.load_settings()
        self.assertEqual(loaded["save_dir"], str(paths.DEFAULT_SAVE_DIR))
        self.assertEqual(loaded["posts_per_file"], 10)
        self.assertTrue(loaded["auto_split"])

    def test_save_dir_roundtrip_persists(self):
        out_dir = self.dir / "Результаты 2026"
        with mock.patch.object(paths, "SETTINGS_FILE", self.settings_file):
            settings_store.save_settings(
                {"save_dir": str(out_dir), "posts_per_file": 7, "auto_split": False}
            )
            loaded = settings_store.load_settings()
        self.assertEqual(loaded["save_dir"], str(out_dir))
        self.assertEqual(loaded["posts_per_file"], 7)
        self.assertFalse(loaded["auto_split"])

    def test_setting_survives_across_processes(self):
        """После 'перезапуска' (повторное чтение файла) папка сохранения та же."""
        out_dir = self.dir / "results"
        with mock.patch.object(paths, "SETTINGS_FILE", self.settings_file):
            settings_store.save_settings({"save_dir": str(out_dir)})
            first = settings_store.load_settings()
            second = settings_store.load_settings()
        self.assertEqual(first["save_dir"], second["save_dir"])
        self.assertEqual(second["save_dir"], str(out_dir))

    def test_unknown_keys_ignored(self):
        with mock.patch.object(paths, "SETTINGS_FILE", self.settings_file):
            settings_store.save_settings({"save_dir": str(self.dir), "save_dir_legacy": "/tmp"})
            loaded = settings_store.load_settings()
            self.assertEqual(loaded["save_dir"], str(self.dir))
            self.assertNotIn("save_dir_legacy", loaded)

    def test_partial_settings_merge_with_defaults(self):
        with mock.patch.object(paths, "SETTINGS_FILE", self.settings_file):
            settings_store.save_settings({"auto_split": False})
            loaded = settings_store.load_settings()
        self.assertFalse(loaded["auto_split"])
        self.assertEqual(loaded["posts_per_file"], 10)


class SaveDirStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="savestatus_test_"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.dir = self.tmp / f"t_{self._testMethodName}"
        self.dir.mkdir(exist_ok=True)

    def test_existing_writable_dir_is_ok(self):
        ok, msg = paths.save_dir_status(self.dir)
        self.assertTrue(ok)
        self.assertEqual(msg, "")

    def test_missing_dir_rejected(self):
        ok, msg = paths.save_dir_status(self.dir / "nonexistent")
        self.assertFalse(ok)
        self.assertIn("Папка сохранения недоступна", msg)

    def test_file_is_not_a_dir(self):
        f = self.dir / "file.txt"
        f.write_text("x", encoding="utf-8")
        ok, msg = paths.save_dir_status(f)
        self.assertFalse(ok)
        self.assertIn("Папка сохранения недоступна", msg)

    def test_readonly_dir_rejected(self):
        ro = self.dir / "ro"
        ro.mkdir()
        ro.chmod(0o500)
        try:
            ok, msg = paths.save_dir_status(ro)
        finally:
            ro.chmod(0o700)
        self.assertFalse(ok)
        self.assertIn("Папка сохранения недоступна", msg)

    def test_no_probe_file_left_behind(self):
        paths.save_dir_status(self.dir)
        self.assertFalse((self.dir / ".write_probe.tmp").exists())


class SaveDirWorkflowTests(unittest.TestCase):
    """REGRESSION: результат Parser и выход Splitter живут в выбранной папке."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="savedir_flow_"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.dir = self.tmp / f"t_{self._testMethodName}"
        self.dir.mkdir(exist_ok=True)

    def test_result_file_for_builds_path(self):
        save = self.dir / "Вакансии"
        self.assertEqual(
            paths.result_file_for(save), save / "telegram_found_posts.txt"
        )

    def test_pipeline_result_file_defaults_to_save_dir(self):
        save = self.dir / "Работа море"
        pipe = Pipeline(current_settings={"save_dir": str(save)})
        self.assertEqual(pipe.result_file, save / "telegram_found_posts.txt")

    def test_full_workflow_writes_into_save_dir(self):
        save = self.dir / "Результаты 2026"
        save.mkdir()
        pipe = Pipeline(
            current_settings={"save_dir": str(save), "auto_split": True, "posts_per_file": 2},
            seen_file=self.dir / "seen.json",
            channels=["c1"],
            keywords=["2nd officer"],
        )
        self.assertEqual(pipe.result_file.parent, save)
        with mock.patch.object(
            parse_mod, "fetch_page", return_value=FakeResponse(text=page_with_posts(5))
        ):
            stage, stats, split_stats = pipe.run_all()
        self.assertEqual(stage, "done")
        self.assertEqual(split_stats.num_posts, 5)
        self.assertEqual((save / "telegram_found_posts.txt").exists(), True)
        batches = sorted((save / "GPT_batches").glob("batch_*.md"))
        self.assertEqual(len(batches), 3)
        for batch in batches:
            self.assertEqual(batch.parent.parent, save)

    def test_result_follows_chosen_dir_after_restart(self):
        """Выбранную в GUI папку сохранили — новый Pipeline использует её же."""
        settings_file = self.dir / "gui_settings.json"
        first_save = self.dir / "first"
        second_save = self.dir / "second"
        with mock.patch.object(paths, "SETTINGS_FILE", settings_file):
            settings_store.save_settings({"save_dir": str(first_save)})
            pipe1 = Pipeline()
            settings_store.save_settings({"save_dir": str(second_save)})
            pipe2 = Pipeline()
        self.assertEqual(pipe1.result_file.parent, first_save)
        self.assertEqual(pipe2.result_file.parent, second_save)
        self.assertNotEqual(pipe1.result_file, pipe2.result_file)

    def test_rerun_split_without_reparse_in_save_dir(self):
        save = self.dir / "out"
        save.mkdir()
        result = save / "telegram_found_posts.txt"
        result.write_text("".join(parse_mod.format_post_block(p) for p in []), encoding="utf-8")
        posts = [f"Текст поста {i}, 2nd officer" for i in range(6)]
        content = "".join(
            parse_mod.format_post_block(
                FoundPost("c1", str(i), f"https://telegram.me/c1/{i}", "2026-09-10", posts[i])
            )
            for i in range(len(posts))
        )
        result.write_text(content, encoding="utf-8")
        pipe = Pipeline(current_settings={"save_dir": str(save), "auto_split": True, "posts_per_file": 3})
        with mock.patch.object(parse_mod, "fetch_page") as fetch:
            split_stats = pipe.split(posts_per_file=3)
        fetch.assert_not_called()
        self.assertEqual(split_stats.num_files, 2)
        self.assertEqual(len(list((save / "GPT_batches").glob("batch_*.md"))), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)