import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.splitter import split as split_mod

SEP = "=" * 80


def post_block(channel="nordvegr", post_id="123", text="2nd officer vacancy", date="2026-09-10"):
    return (
        f"{SEP}\n"
        f"КАНАЛ: {channel}\n"
        f"ID: {post_id}\n"
        f"ССЫЛКА: https://telegram.me/{channel}/{post_id}\n"
        f"ДАТА: {date}\n"
        f"{SEP}\n\n"
        f"{text}\n\n"
    )


def make_result_file(dir_path, n_posts):
    content = "".join(post_block(post_id=str(i + 1), text=f"Post {i + 1}") for i in range(n_posts))
    f = Path(dir_path) / "result.txt"
    f.write_text(content, encoding="utf-8")
    return f


class SplitterLogicTests(unittest.TestCase):
    def test_split_posts_normal(self):
        text = post_block(post_id="1", text="пост A") + post_block(post_id="2", text="пост B")
        posts = split_mod.split_posts(text)
        self.assertEqual(len(posts), 2)
        self.assertIn("КАНАЛ: nordvegr", posts[0])
        self.assertIn("пост B", posts[1])

    def test_split_posts_empty(self):
        self.assertEqual(split_mod.split_posts(""), [])
        self.assertEqual(split_mod.split_posts("   \n\n  "), [])
        self.assertEqual(split_mod.split_posts("просто текст без разделителей"), [])

    def test_split_posts_small_file(self):
        posts = split_mod.split_posts(post_block(post_id="1"))
        self.assertEqual(len(posts), 1)

    def test_split_posts_no_trailing_separator(self):
        block = f"{SEP}\nКАНАЛ: c\nID: 5\nССЫЛКА: x\nДАТА: d\n{SEP}\n\nтекст"
        posts = split_mod.split_posts(block)
        self.assertEqual(len(posts), 1)
        self.assertIn("текст", posts[0])

    def test_output_dir_placement(self):
        source = Path("/tmp/x/results") / "file.txt"
        self.assertEqual(split_mod.get_output_dir(source), Path("/tmp/x/results") / "GPT_batches")


class SplitterRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="split_test_"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_run_split_normal(self):
        source = make_result_file(self.tmp, 5)
        out_dir = self.tmp / "GPT_batches"
        stats = split_mod.run_split(source, posts_per_file=2, output_dir=out_dir)
        self.assertEqual(stats.num_posts, 5)
        self.assertEqual(stats.num_files, 3)
        files = sorted(out_dir.glob("batch_*.md"))
        self.assertEqual(len(files), 3)
        self.assertEqual(files[0].name, "batch_001.md")
        content = files[0].read_text(encoding="utf-8")
        self.assertTrue(content.startswith("# Telegram vacancy batch"))
        self.assertIn("Post 1", content)
        self.assertIn("Post 2", content)
        self.assertNotIn("Post 3", content)

    def test_run_split_deletes_old_batches(self):
        source = make_result_file(self.tmp, 3)
        out_dir = self.tmp / "GPT_batches"
        out_dir.mkdir(exist_ok=True)
        (out_dir / "batch_001.md").write_text("СТАРЫЙ", encoding="utf-8")
        (out_dir / "batch_002.md").write_text("СТАРЫЙ", encoding="utf-8")
        split_mod.run_split(source, posts_per_file=10, output_dir=out_dir)
        files = list(out_dir.glob("batch_*.md"))
        self.assertEqual(len(files), 1)
        self.assertNotIn("СТАРЫЙ", files[0].read_text(encoding="utf-8"))

    def test_run_split_empty_file_zero_batches(self):
        source = make_result_file(self.tmp, 0)
        out_dir = self.tmp / "GPT_batches_empty"
        stats = split_mod.run_split(source, posts_per_file=10, output_dir=out_dir)
        self.assertEqual(stats.num_posts, 0)
        self.assertEqual(stats.num_files, 0)
        self.assertEqual(list(out_dir.glob("batch_*.md")), [])

    def test_run_split_missing_source(self):
        with self.assertRaises(FileNotFoundError):
            split_mod.run_split(self.tmp / "нет_такого.txt", output_dir=self.tmp / "x")

    def test_run_split_bad_posts_per_file(self):
        source = make_result_file(self.tmp, 1)
        with self.assertRaises(ValueError):
            split_mod.run_split(source, posts_per_file=0, output_dir=self.tmp / "x")

    def test_run_split_large_file(self):
        source = make_result_file(self.tmp, 123)
        out_dir = self.tmp / "GPT_batches_large"
        stats = split_mod.run_split(source, posts_per_file=10, output_dir=out_dir)
        self.assertEqual(stats.num_posts, 123)
        self.assertEqual(stats.num_files, 13)


if __name__ == "__main__":
    unittest.main(verbosity=2)