import json
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.parser import parse as parse_mod
from app.parser.keywords import NORMALIZED_KEYWORDS, normalize_keywords
from app.parser.scraper import parse_channel_posts


def channel_page_html(posts):
    """posts: list[(message_id, text)] -> HTML, похожий на telegram.me/s/..."""
    block = []
    for post_id, text in posts:
        block.append(
            '<div class="tgme_widget_message_wrap">'
            '<div class="tgme_widget_message_date">'
            '<a class="tgme_widget_message_date" href="/testchan/{id}">'
            '<time datetime="2026-09-10T12:00:00"></time>'
            "</a></div>"
            '<div class="tgme_widget_message_text">{text}</div>'
            "</div>".format(id=post_id, text=text.replace("\n", "<br/>"))
        )
    return "<html><body>" + "".join(block) + "</body></html>"


def page_with_posts(n_posts):
    texts = [f"Вакансия: 2nd officer, танкер, ID {i}" for i in range(n_posts)]
    return channel_page_html(list(zip([str(i + 1) for i in range(n_posts)], texts)))


class FakeResponse:
    def __init__(self, status_code=200, text="", headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class KeywordTests(unittest.TestCase):
    def test_normalized_keywords_present(self):
        self.assertIn("secondofficer".lower(), NORMALIZED_KEYWORDS)
        self.assertIn("2ndofficer", NORMALIZED_KEYWORDS)
        self.assertIn("второйпомощниккапитана", NORMALIZED_KEYWORDS)

    def test_normalize_helper(self):
        self.assertEqual(normalize_keywords([" Второй Помощник "]), ["второйпомощник"])


class ScraperTests(unittest.TestCase):
    def test_finds_matching_post(self):
        html = channel_page_html([("1", "Vacancy: 2nd officer needed")])
        found, stats = parse_channel_posts(html, "testchan", {}, NORMALIZED_KEYWORDS)
        self.assertEqual(stats.posts_checked, 1)
        self.assertEqual(stats.posts_found, 1)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].message_id, "1")
        self.assertEqual(found[0].link, "https://telegram.me/testchan/1")
        self.assertEqual(found[0].post_date, "2026-09-10")

    def test_skips_non_matching_post(self):
        html = channel_page_html([("1", "Купим мазут оптом")])
        found, stats = parse_channel_posts(html, "testchan", {}, NORMALIZED_KEYWORDS)
        self.assertEqual(stats.posts_checked, 1)
        self.assertEqual(stats.posts_found, 0)
        self.assertEqual(found, [])

    def test_skips_already_seen_post(self):
        html = channel_page_html([("1", "Vacancy: 2nd officer"), ("2", "Vacancy: 3rd mate")])
        found, stats = parse_channel_posts(html, "testchan", {"testchan": ["1"]}, NORMALIZED_KEYWORDS)
        self.assertEqual(stats.posts_checked, 1)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].message_id, "2")

    def test_cyrillic_keyword_match(self):
        html = channel_page_html([("1", "Требуется ВТОРОЙ ПОМОЩНИК на сухогруз")])
        found, _ = parse_channel_posts(html, "testchan", {}, NORMALIZED_KEYWORDS)
        self.assertEqual(len(found), 1)

    def test_post_without_date_does_not_crash(self):
        html = (
            '<div class="tgme_widget_message_wrap">'
            '<div class="tgme_widget_message_text">2 officer urgent</div>'
            "</div>"
        )
        found, stats = parse_channel_posts(html, "testchan", {}, NORMALIZED_KEYWORDS)
        self.assertEqual(found[0].message_id, "?")
        self.assertEqual(found[0].link, "-")
        self.assertEqual(stats.posts_checked, 1)


class ParseRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="parse_test_"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.dir = self.tmp / f"t_{self._testMethodName}"
        self.dir.mkdir(exist_ok=True)
        self.result = self.dir / "out.txt"
        self.seen = self.dir / "seen.json"

    def test_run_parse_writes_result_in_original_format(self):
        with mock.patch.object(parse_mod, "fetch_page", return_value=FakeResponse(text=page_with_posts(3))):
            stats = parse_mod.run_parse(
                result_file=self.result, seen_file=self.seen, channel_list=["chan1", "chan2"],
                keywords=["2nd officer"],
            )
        self.assertEqual(stats.channels_checked, 2)
        self.assertEqual(stats.channels_ok, 2)
        self.assertEqual(stats.posts_found, 6)
        text = self.result.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("=" * 80))
        self.assertIn("КАНАЛ: chan1", text)
        self.assertIn("ССЫЛКА: https://telegram.me/testchan/1", text)
        self.assertEqual(text.count("КАНАЛ:"), 6)

        seen_data = json.loads(self.seen.read_text(encoding="utf-8"))
        self.assertIn("1", seen_data["chan1"])
        self.assertEqual(len(seen_data["chan1"]), 3)

    def test_dedup_across_runs(self):
        self.seen.write_text(json.dumps({"chan1": ["1", "2"]}), encoding="utf-8")
        with mock.patch.object(parse_mod, "fetch_page", return_value=FakeResponse(text=page_with_posts(3))):
            stats = parse_mod.run_parse(
                result_file=self.result, seen_file=self.seen, channel_list=["chan1"], keywords=["2nd officer"]
            )
        self.assertEqual(stats.posts_found, 1)
        self.assertEqual(self.result.read_text(encoding="utf-8").count("КАНАЛ:"), 1)

    def test_cancel_between_channels(self):
        stop = threading.Event()
        stop.set()

        class Pager:
            def __init__(self, html):
                self._html = html

            def __call__(self, channel):
                return FakeResponse(text=self._html)

        with mock.patch.object(parse_mod, "fetch_page", Pager(page_with_posts(1))):
            stats = parse_mod.run_parse(
                result_file=self.result, seen_file=self.seen, channel_list=["c1", "c2", "c3"],
                stop_event=stop, keywords=["2nd officer"],
            )
        self.assertEqual(stats.cancelled, True)
        self.assertEqual(stats.channels_checked, 0)
        self.assertEqual(stats.posts_found, 0)

    def test_empty_channels_raises(self):
        with self.assertRaises(ValueError):
            parse_mod.run_parse(
                result_file=self.result, seen_file=self.seen, channel_list=[], keywords=["2nd officer"]
            )

    def test_channel_error_continues_to_next(self):
        def flaky(channel):
            if channel == "bad":
                raise OSError("connection refused")
            return FakeResponse(text=page_with_posts(1))

        with mock.patch.object(parse_mod, "fetch_page", side_effect=flaky):
            stats = parse_mod.run_parse(
                result_file=self.result, seen_file=self.seen, channel_list=["good", "bad", "good2"],
                keywords=["2nd officer"],
            )
        self.assertEqual(stats.channels_ok, 2)
        self.assertEqual(len(stats.failed_channels), 1)
        self.assertEqual(stats.posts_found, 2)

    def test_redirect_and_http_error_skips_channel(self):
        def responder(channel):
            if channel == "r":
                return FakeResponse(status_code=301, headers={"Location": "https://x"})
            if channel == "h":
                return FakeResponse(status_code=404)
            return FakeResponse(text=page_with_posts(2))

        with mock.patch.object(parse_mod, "fetch_page", side_effect=responder):
            stats = parse_mod.run_parse(
                result_file=self.result, seen_file=self.seen, channel_list=["r", "h", "ok"],
                keywords=["2nd officer"],
            )
        self.assertEqual(stats.channels_ok, 1)
        self.assertEqual(stats.posts_found, 2)

    def test_seen_file_saved_even_on_cancel(self):
        stop = threading.Event()

        def pager(channel):
            stop.set()
            return FakeResponse(text=page_with_posts(1))

        with mock.patch.object(parse_mod, "fetch_page", side_effect=pager):
            parse_mod.run_parse(
                result_file=self.result, seen_file=self.seen, channel_list=["c1"],
                stop_event=stop, keywords=["2nd officer"],
            )
        self.assertTrue(self.seen.exists())


class FormatTests(unittest.TestCase):
    def test_format_post_block_matches_original(self):
        from app.parser.scraper import FoundPost

        post = FoundPost(channel="ch", message_id="42", link="https://telegram.me/ch/42", post_date="2026-01-01", text="текст")
        block = parse_mod.format_post_block(post)
        expected = (
            f"{'=' * 80}\nКАНАЛ: ch\nID: 42\nССЫЛКА: https://telegram.me/ch/42\nДАТА: 2026-01-01\n"
            f"{'=' * 80}\n\nтекст\n\n"
        )
        self.assertEqual(block, expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)