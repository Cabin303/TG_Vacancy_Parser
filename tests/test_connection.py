import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.test_parser import FakeResponse, page_with_posts

from app.core import connection as conn
from app.parser import parse as parse_mod
from app.runner import ConnectionBlockedError, Pipeline, PipelineError
from app import runner as runner_mod


def fake_probe(internet: bool = True, telegram: bool = True):
    def probe(url, timeout):
        if url == conn.INTERNET_PROBE_URL:
            return internet
        if url == conn.TELEGRAM_PROBE_URL:
            return telegram
        return False

    return probe


class CheckConnectionTests(unittest.TestCase):
    def test_internet_and_telegram_ok(self):
        state = conn.check_connection(timeout=1, probe=fake_probe())
        self.assertTrue(state.usable_for_parser())
        self.assertEqual(state.label, "Интернет: OK | Telegram: OK")
        self.assertEqual(state.color, "#2e8b57")

    def test_internet_unavailable(self):
        state = conn.check_connection(timeout=1, probe=fake_probe(internet=False))
        self.assertIs(state.internet, False)
        self.assertIsNone(state.telegram)
        self.assertFalse(state.usable_for_parser())
        self.assertIn("нет соединения", state.label)
        self.assertEqual(state.color, "#cc0000")

    def test_telegram_unavailable(self):
        state = conn.check_connection(timeout=1, probe=fake_probe(telegram=False))
        self.assertIs(state.internet, True)
        self.assertIs(state.telegram, False)
        self.assertEqual(state.label, "Интернет: OK | Telegram: недоступен")
        self.assertFalse(state.usable_for_parser())
        self.assertEqual(state.color, "#c9a100")

    def test_telegram_restored(self):
        down = conn.check_connection(timeout=1, probe=fake_probe(telegram=False))
        up = conn.check_connection(timeout=1, probe=fake_probe(telegram=True))
        self.assertFalse(down.usable_for_parser())
        self.assertTrue(up.usable_for_parser())
        self.assertEqual(up.label, "Интернет: OK | Telegram: OK")
        self.assertEqual(up.color, "#2e8b57")

    def test_initial_state_is_checking(self):
        state = conn.ConnectionState()
        self.assertIsNone(state.internet)
        self.assertEqual(state.label, "Проверка соединения...")
        self.assertEqual(state.color, "#c9a100")
        self.assertFalse(state.usable_for_parser())

    def test_probe_network_error_returns_false(self):
        with mock.patch.object(
            conn.requests, "get", side_effect=conn.requests.ConnectionError("down")
        ):
            self.assertFalse(conn._probe(conn.INTERNET_PROBE_URL, timeout=1))

    def test_probe_any_http_response_means_reachable(self):
        with mock.patch.object(conn.requests, "get", return_value=FakeResponse(status_code=503)):
            self.assertTrue(conn._probe(conn.INTERNET_PROBE_URL, timeout=1))

    def test_internet_not_probed_via_interface_only(self):
        """Интернет определяется реальным HTTP-ответом, а не наличием интерфейса."""
        with mock.patch.object(conn.requests, "get", side_effect=OSError("no route")):
            state = conn.check_connection(timeout=1)
        self.assertIs(state.internet, False)


class ConnectionMonitorTests(unittest.TestCase):
    def _monitor(self, interval=10):
        return conn.ConnectionMonitor(interval=interval, check=lambda timeout: None)

    def test_due_before_first_check(self):
        monitor = self._monitor()
        self.assertTrue(monitor.due(now=100.0))

    def test_not_due_within_interval(self):
        monitor = self._monitor(interval=10)
        self.assertTrue(monitor.begin_check(now=0.0))
        monitor.finish_check()
        self.assertFalse(monitor.due(now=5.0))
        self.assertTrue(monitor.due(now=10.0))

    def test_single_flight_blocks_second_start(self):
        gate = threading.Event()

        def slow_check(timeout=None):
            gate.wait(5)
            return conn.ConnectionState(internet=True, telegram=True)

        monitor = conn.ConnectionMonitor(interval=10, check=slow_check)
        self.assertTrue(monitor.begin_check())
        self.assertTrue(monitor._in_flight)
        self.assertFalse(monitor.due())
        # вторая проверка не стартует, пока первая в полёте
        self.assertFalse(monitor.begin_check())
        gate.set()
        monitor.finish_check()
        self.assertFalse(monitor._in_flight)
        # флажок освобождён: проверку можно запустить снова
        self.assertTrue(monitor.begin_check())
        monitor.finish_check()

    def test_run_once_is_nonblocking(self):
        """Проверка выполняется в потоке: run_once не ждёт завершения (GUI не зависает)."""
        started = []

        def slow_check(timeout=None):
            started.append(time.monotonic())
            time.sleep(1.0)
            return conn.ConnectionState(internet=True, telegram=True)

        monitor = conn.ConnectionMonitor(interval=0, check=slow_check)
        t0 = time.monotonic()
        self.assertTrue(monitor.run_once(timeout=1))
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 0.5)
        for _ in range(100):
            if not monitor._in_flight:
                break
            time.sleep(0.02)
        self.assertFalse(monitor._in_flight)

    def test_run_once_single_flight(self):
        gate = threading.Event()

        def slow_check(timeout=None):
            gate.wait(5)
            return conn.ConnectionState(internet=True, telegram=True)

        monitor = conn.ConnectionMonitor(interval=0, check=slow_check)
        self.assertTrue(monitor.run_once(timeout=1))
        # первая проверка ещё выполняется (поток держим на gate) — вторая не стартует
        self.assertFalse(monitor.run_once(timeout=1))
        gate.set()
        for _ in range(100):
            if not monitor._in_flight:
                break
            time.sleep(0.02)
        self.assertFalse(monitor._in_flight)


class ParserConnectionGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="conn_gate_"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.dir = self.tmp / f"t_{self._testMethodName}"
        self.dir.mkdir(exist_ok=True)

    def _pipe(self, checker):
        return Pipeline(
            current_settings={"save_dir": str(self.dir), "auto_split": True, "posts_per_file": 10},
            result_file=self.dir / "out.txt",
            seen_file=self.dir / "seen.json",
            channels=["c1"],
            keywords=["2nd officer"],
            connection_checker=checker,
        )

    def test_parser_not_launched_without_internet(self):
        def checker():
            return conn.ConnectionState(internet=False, telegram=None)

        with mock.patch.object(parse_mod, "fetch_page") as fetch:
            with self.assertRaises(ConnectionBlockedError) as ctx:
                self._pipe(checker).parse()
        fetch.assert_not_called()
        self.assertIn("Интернет отсутствует", str(ctx.exception))

    def test_parser_not_launched_when_telegram_down(self):
        def checker():
            return conn.ConnectionState(internet=True, telegram=False)

        with mock.patch.object(parse_mod, "fetch_page") as fetch:
            with self.assertRaises(ConnectionBlockedError) as ctx:
                self._pipe(checker).parse()
        fetch.assert_not_called()
        self.assertEqual(str(ctx.exception), "Интернет доступен, но Telegram недоступен.")

    def test_parser_runs_when_connection_ok(self):
        def checker():
            return conn.ConnectionState(internet=True, telegram=True)

        with mock.patch.object(
            parse_mod, "fetch_page", return_value=FakeResponse(text=page_with_posts(1))
        ) as fetch:
            stats = self._pipe(checker).parse()
        fetch.assert_called_once()
        self.assertEqual(stats.posts_found, 1)

    def test_connection_blocked_stops_workflow_before_split(self):
        def checker():
            return conn.ConnectionState(internet=False, telegram=None)

        pipe = self._pipe(checker)
        with mock.patch.object(parse_mod, "fetch_page") as fetch:
            with mock.patch.object(runner_mod, "run_split") as split:
                with self.assertRaises(ConnectionBlockedError):
                    pipe.run_all()
        fetch.assert_not_called()
        split.assert_not_called()
        self.assertTrue(issubclass(ConnectionBlockedError, PipelineError))


if __name__ == "__main__":
    unittest.main(verbosity=2)