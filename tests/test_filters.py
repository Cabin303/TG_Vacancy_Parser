import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.test_parser import FakeResponse, channel_page_html, page_with_posts

from app.core import filters as filters_store
from app.parser import parse as parse_mod
from app.parser.keywords import KEYWORDS, normalize_keywords
from app.parser.scraper import parse_channel_posts


class FiltersStorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="filters_test_"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.dir = self.tmp / f"t_{self._testMethodName}"
        self.dir.mkdir(exist_ok=True)
        self.file = self.dir / "vacancy_filters.json"

    def test_first_run_migrates_existing_filters(self):
        self.assertFalse(self.file.exists())
        entries = filters_store.load_filters(self.file)
        self.assertTrue(self.file.exists())
        self.assertEqual([e["name"] for e in entries], KEYWORDS)
        self.assertTrue(all(e["enabled"] for e in entries))

    def test_load_existing_filters(self):
        self.file.write_text(
            json.dumps(
                [
                    {"name": "Second Officer", "enabled": True},
                    {"name": "Third Officer", "enabled": False},
                ]
            ),
            encoding="utf-8",
        )
        entries = filters_store.load_filters(self.file)
        self.assertEqual(entries[0]["name"], "Second Officer")
        self.assertTrue(entries[0]["enabled"])
        self.assertFalse(entries[1]["enabled"])

    def test_save_roundtrip_persists(self):
        entries = filters_store.add_filter(filters_store.load_filters(self.file), "Chief Officer")
        filters_store.save_filters(entries, self.file)
        loaded = filters_store.load_filters(self.file)
        names = [e["name"] for e in loaded]
        self.assertIn("Chief Officer", names)
        self.assertGreaterEqual(len(loaded), 1)
        self.assertTrue(all(e["enabled"] for e in loaded))

    def test_add_edit_remove_toggle_helpers(self):
        base = [{"name": "A", "enabled": True}]
        added = filters_store.add_filter(base, "  B  ")
        self.assertEqual(len(added), 2)
        self.assertTrue(added[1]["enabled"])
        self.assertEqual(added[1]["name"], "B")
        edited = filters_store.update_filter(added, 0, "A2")
        self.assertEqual(edited[0]["name"], "A2")
        self.assertEqual(edited[1]["name"], "B")
        toggled = filters_store.toggle_filter(edited, 1)
        self.assertFalse(toggled[1]["enabled"])
        removed = filters_store.remove_filter(toggled, 0)
        self.assertEqual([e["name"] for e in removed], ["B"])

    def test_active_names_only_enabled(self):
        entries = [
            {"name": "Second Officer", "enabled": True},
            {"name": "Third Officer", "enabled": False},
        ]
        self.assertEqual(filters_store.active_names(entries), ["Second Officer"])

    def test_empty_list_is_preserved(self):
        self.file.write_text("[]", encoding="utf-8")
        self.assertEqual(filters_store.load_filters(self.file), [])
        self.assertEqual(filters_store.active_names([]), [])
        filters_store.save_filters([], self.file)
        self.assertEqual(filters_store.load_filters(self.file), [])

    def test_corrupt_file_falls_back_to_legacy_list(self):
        self.file.write_text("{this is not json", encoding="utf-8")
        entries = filters_store.load_filters(self.file)
        self.assertEqual([e["name"] for e in entries], KEYWORDS)
        filters_store.save_filters(entries, self.file)
        self.assertEqual(filters_store.load_filters(self.file), entries)

    def test_schema_normalization_drops_junk(self):
        self.file.write_text(
            json.dumps([{"name": "  ok  "}, {"enabled": True}, 5, "text"]),
            encoding="utf-8",
        )
        entries = filters_store.load_filters(self.file)
        self.assertEqual(entries, [{"name": "ok", "enabled": True}])


HTML_BOTH = channel_page_html(
    [("1", "Need 2nd officer for tanker"), ("2", "Need 3rd officer for bulk")]
)


class ParserUsesEnabledFiltersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="filters_parser_"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.dir = self.tmp / f"t_{self._testMethodName}"
        self.dir.mkdir(exist_ok=True)
        self.result = self.dir / "out.txt"
        self.seen = self.dir / "seen.json"

    def test_only_enabled_phrases_match(self):
        entries = [
            {"name": "2nd officer", "enabled": True},
            {"name": "3rd officer", "enabled": False},
        ]
        normalized = normalize_keywords(filters_store.active_names(entries))
        found, stats = parse_channel_posts(HTML_BOTH, "c", {}, normalized)
        self.assertEqual(stats.posts_found, 1)
        self.assertIn("2nd officer", found[0].text)

    def test_all_disabled_finds_nothing(self):
        entries = [
            {"name": "2nd officer", "enabled": False},
            {"name": "3rd officer", "enabled": False},
        ]
        normalized = normalize_keywords(filters_store.active_names(entries))
        found, stats = parse_channel_posts(HTML_BOTH, "c", {}, normalized)
        self.assertEqual(stats.posts_checked, 2)
        self.assertEqual(stats.posts_found, 0)
        self.assertEqual(found, [])

    def test_run_parse_explicit_keywords(self):
        with mock.patch.object(
            parse_mod, "fetch_page", return_value=FakeResponse(text=page_with_posts(2))
        ):
            stats = parse_mod.run_parse(
                result_file=self.result,
                seen_file=self.seen,
                channel_list=["c1"],
                keywords=["2nd officer"],
            )
        self.assertEqual(stats.posts_found, 2)

    def test_run_parse_disabled_phrase_not_used(self):
        with mock.patch.object(
            parse_mod, "fetch_page", return_value=FakeResponse(text=page_with_posts(2))
        ):
            stats = parse_mod.run_parse(
                result_file=self.result,
                seen_file=self.seen,
                channel_list=["c1"],
                keywords=["3rd officer"],
            )
        self.assertEqual(stats.posts_found, 0)

    def test_run_parse_empty_keywords_finds_nothing(self):
        with mock.patch.object(
            parse_mod, "fetch_page", return_value=FakeResponse(text=page_with_posts(2))
        ):
            stats = parse_mod.run_parse(
                result_file=self.result,
                seen_file=self.seen,
                channel_list=["c1"],
                keywords=[],
            )
        self.assertEqual(stats.posts_found, 0)

    def test_default_keywords_come_from_filters_file(self):
        file = self.dir / "vacancy_filters.json"
        file.write_text(
            json.dumps(
                [
                    {"name": "2nd officer", "enabled": True},
                    {"name": "3rd officer", "enabled": False},
                ]
            ),
            encoding="utf-8",
        )
        html = channel_page_html(
            [("1", "Need 2nd officer"), ("2", "Need 3rd officer")]
        )
        with mock.patch.object(filters_store, "FILTERS_FILE", file):
            with mock.patch.object(
                parse_mod, "fetch_page", return_value=FakeResponse(text=html)
            ):
                stats = parse_mod.run_parse(
                    result_file=self.result,
                    seen_file=self.seen,
                    channel_list=["c1"],
                )
        self.assertEqual(stats.posts_found, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)