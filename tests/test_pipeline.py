import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.test_parser import FakeResponse, page_with_posts
from app.parser import parse as parse_mod
from app.runner import Pipeline, PipelineError

import unittest


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="pipe_test_"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.dir = self.tmp / f"t_{self._testMethodName}"
        self.dir.mkdir(exist_ok=True)

    def _pipeline(self, auto_split=True, posts_per_file=10, channels=None):
        return Pipeline(
            current_settings={"auto_split": auto_split, "posts_per_file": posts_per_file},
            result_file=self.dir / "out.txt",
            seen_file=self.dir / "seen.json",
            channels=channels or ["c1", "c2"],
            keywords=["2nd officer"],
        )

    def test_run_all_success(self):
        pipe = self._pipeline(auto_split=True, posts_per_file=2, channels=["c1"])
        with mock.patch.object(parse_mod, "fetch_page", return_value=FakeResponse(text=page_with_posts(5))):
            stage, stats, split_stats = pipe.run_all()
        self.assertEqual(stage, "done")
        self.assertEqual(stats.posts_found, 5)
        self.assertEqual(split_stats.num_posts, 5)
        self.assertEqual(split_stats.num_files, 3)
        self.assertTrue((self.dir / "out.txt").exists())
        self.assertTrue((self.dir / "seen.json").exists())

    def test_run_all_partial_when_autosplit_off(self):
        pipe = self._pipeline(auto_split=False)
        with mock.patch.object(parse_mod, "fetch_page", return_value=FakeResponse(text=page_with_posts(3))):
            stage, stats, split_stats = pipe.run_all()
        self.assertEqual(stage, "partial")
        self.assertIsNone(split_stats)
        self.assertEqual(stats.posts_found, 6)

    def test_parser_error_prevents_split(self):
        pipe = self._pipeline(auto_split=True, channels=["c1"])

        def boom(channel):
            raise OSError("network down")

        with mock.patch.object(parse_mod, "fetch_page", side_effect=boom):
            with self.assertRaises(PipelineError):
                pipe.run_all()
        # Результат при полном отказе полностью пуст — Splitter не запускается
        self.assertTrue((self.dir / "out.txt").exists())
        self.assertEqual((self.dir / "out.txt").stat().st_size, 0)

    def test_parser_error_still_preserves_partial_result(self):
        """Если часть каналов удалась, результат должен сохраниться, и его можно разбить позже."""
        pipe_parse = self._pipeline(auto_split=False, channels=["good", "bad"])

        def flaky(channel):
            if channel == "bad":
                raise OSError("error")
            return FakeResponse(text=page_with_posts(2))

        with mock.patch.object(parse_mod, "fetch_page", side_effect=flaky):
            stats = pipe_parse.parse()
        self.assertEqual(stats.posts_found, 2)
        self.assertTrue((self.dir / "out.txt").exists())

        # Повторный запуск ТОЛЬКО Splitter на сохранённом результате
        split_stats = self._pipeline(auto_split=False).split(posts_per_file=2, output_dir=self.dir / "GPT_batches")
        self.assertEqual(split_stats.num_posts, 2)
        self.assertEqual(split_stats.num_files, 1)

    def test_rerun_split_without_reparse(self):
        # Единожды парсим
        with mock.patch.object(parse_mod, "fetch_page", return_value=FakeResponse(text=page_with_posts(6))):
            self._pipeline(auto_split=False).parse()
        # Split запускаем повторно (дважды) — результаты должны быть одинаковы и не требовать парсинга
        first = self._pipeline(auto_split=False).split(posts_per_file=3, output_dir=self.dir / "GPT_batches")
        self.assertEqual(first.num_posts, 12)
        self.assertEqual(first.num_files, 4)
        first_files = {f.name: f.read_text(encoding="utf-8") for f in (self.dir / "GPT_batches").glob("batch_*.md")}
        second = self._pipeline(auto_split=False).split(posts_per_file=3, output_dir=self.dir / "GPT_batches")
        second_files = {f.name: f.read_text(encoding="utf-8") for f in (self.dir / "GPT_batches").glob("batch_*.md")}
        self.assertEqual(second.num_files, 4)
        self.assertEqual(first_files, second_files)

    def test_full_rerun(self):
        first = self._pipeline(auto_split=True, posts_per_file=2)
        with mock.patch.object(parse_mod, "fetch_page", return_value=FakeResponse(text=page_with_posts(4))):
            stage1, stats1, split1 = first.run_all()
        # второй полный прогон: те же посты уже в seen -> ничего нового
        second = self._pipeline(auto_split=True, posts_per_file=2)
        with mock.patch.object(parse_mod, "fetch_page", return_value=FakeResponse(text=page_with_posts(4))):
            stage2, stats2, split2 = second.run_all()
        self.assertEqual(stage1, "done")
        self.assertEqual(stage2, "done")
        self.assertEqual(stats1.posts_found, 8)
        self.assertEqual(stats2.posts_found, 0)
        self.assertEqual(split2.num_posts, 0)


class IntegrationBridgeTests(unittest.TestCase):
    """Мост Parser→Splitter: вывод parser.parse разбирается split_posts корректно."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="bridge_test_"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_parser_output_is_splitter_ready(self):
        from app.splitter.split import split_posts

        from app.parser.scraper import FoundPost
        posts = [
            FoundPost("ch1", "1", "https://telegram.me/ch1/1", "2026-01-01", "текст один"),
            FoundPost("ch2", "2", "https://telegram.me/ch2/2", "2026-01-02", "текст два"),
        ]
        content = "".join(parse_mod.format_post_block(p) for p in posts)
        parsed = split_posts(content)
        self.assertEqual(len(parsed), 2)
        self.assertIn("КАНАЛ: ch1", parsed[0])
        self.assertIn("текст два", parsed[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)