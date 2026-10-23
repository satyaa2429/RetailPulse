"""Independent worker lifecycle and safe import; Windows shell integration is separate."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import Request, urlopen
from wsgiref.simple_server import make_server
from threading import Thread
from unittest.mock import patch
import json
import os
import socket
import sqlite3
import subprocess
import sys
import unittest
from retailpulse.desktop import (DEFAULT_PORT, SERVICE, app_home, atomic_json, control_request,
                                ensure_running, import_data, open_window, stop_worker, worker_lock)
from retailpulse.store import Store


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "Satya Shop installation"
        self.source = Path(self.temp.name) / "old shop-data"

    def seed(self):
        store = Store(self.source)
        store.initialize_shop({"request_id": "setup", "shop_name": "Satya Shop"})
        store.save_product({"request_id": "item", "sku": "TEA", "name": "Tea", "unit_price": "20", "opening_stock": 25})
        store.checkout({"bill_id": "old-bill", "customer_phone": "9000000000", "items": [{"sku": "TEA", "quantity": 2, "unit_price": "20"}]})
        return store

    def request(self, ready, path, payload=None):
        raw = None if payload is None else json.dumps(payload).encode()
        request = Request(ready["url"].rstrip("/") + path, data=raw,
                          headers={} if raw is None else {"Content-Type": "application/json"})
        with urlopen(request, timeout=5) as response:
            body = response.read()
            return json.loads(body) if response.headers.get_content_type() == "application/json" else body

    def cleanup_worker(self):
        try:
            stop_worker(self.home)
        except RuntimeError:
            pass

    def test_worker_survives_launcher_exit_and_reopens_with_same_records(self):
        self.addCleanup(self.cleanup_worker)
        code = "from retailpulse.desktop import ensure_running; import json,sys; r=ensure_running(sys.argv[1]); print(json.dumps({'pid':r['pid'],'instance':r['instance'],'url':r['url']}))"
        parent = subprocess.run([sys.executable, "-c", code, str(self.home)], cwd=Path(__file__).resolve().parent.parent,
                                capture_output=True, text=True, timeout=45, check=True)
        ready = json.loads(parent.stdout)
        self.assertEqual(control_request(self.home)["instance"], ready["instance"])
        self.assertTrue(self.request(ready, "/api/state")["desktop_mode"])
        self.request(ready, "/api/setup", {"request_id": "setup", "shop_name": "Satya Shop"})
        self.request(ready, "/api/products", {"request_id": "item", "sku": "SOAP", "name": "Soap", "unit_price": "30", "opening_stock": 20})
        self.request(ready, "/api/checkout", {"bill_id": "desktop-bill", "customer_phone": "9000000000", "items": [{"sku": "SOAP", "quantity": 3, "unit_price": "30"}]})
        identity = self.request(ready, "/api/state")["metadata"]["store_id"]
        again = ensure_running(self.home)
        self.assertEqual((again["pid"], again["instance"]), (ready["pid"], ready["instance"]))
        self.assertTrue(stop_worker(self.home))
        restarted = ensure_running(self.home)
        self.assertNotEqual(restarted["instance"], ready["instance"])
        self.assertEqual(restarted["port"], again["port"])
        state = self.request(restarted, "/api/state")
        self.assertEqual(state["metadata"]["store_id"], identity)
        self.assertEqual(state["products"][0]["stock"], 17)
        self.assertEqual(self.request(restarted, "/api/bills/desktop-bill")["customer_phone"], "919000000000")
        html = self.request(restarted, "/")
        self.assertIn(b'id="top-nav"', html)
        self.assertNotIn(b'id="sidebar"', html)

    def test_parallel_icon_clicks_start_one_worker(self):
        self.addCleanup(self.cleanup_worker)
        with ThreadPoolExecutor(4) as pool:
            results = list(pool.map(lambda _: ensure_running(self.home), range(4)))
        self.assertEqual(len({r["instance"] for r in results}), 1)
        self.assertEqual(len({r["pid"] for r in results}), 1)
        self.assertEqual(len({r["url"] for r in results}), 1)
        self.assertEqual(Store(self.home / "data").rows("SELECT * FROM events"), [])

    def test_occupied_port_is_skipped_and_unauthorized_stop_cannot_quit_worker(self):
        self.addCleanup(self.cleanup_worker)
        with closing(socket.socket()) as other:
            other.bind(("127.0.0.1", 0))
            other.listen()
            atomic_json(self.home / "run" / "last-port.json", {"port": other.getsockname()[1]})
            ready = ensure_running(self.home)
            self.assertNotEqual(ready["port"], other.getsockname()[1])
            with self.assertRaises(Exception) as captured:
                self.request(ready, "/_satya_desktop/stop", {})
            self.assertEqual(getattr(captured.exception, "code", None), 403)
            self.assertIsNotNone(control_request(self.home))
            with self.assertRaises(Exception) as captured:
                self.request(ready, "/_satya_desktop/status")
            self.assertEqual(getattr(captured.exception, "code", None), 403)
            self.assertTrue(self.request(ready, "/api/status")["ok"])

    def test_stale_or_malformed_marker_does_not_reuse_wrong_app(self):
        marker = self.home / "run" / "server.json"
        for record in [{}, {"service": SERVICE, "port": True, "key": "x" * 64},
                       {"service": "other-app", "port": 8000, "key": "x" * 64},
                       {"service": SERVICE, "port": 8000, "key": "x" * 64, "home_id": "different-home"}]:
            atomic_json(marker, record)
            self.assertIsNone(control_request(self.home))
        self.addCleanup(self.cleanup_worker)
        ready = ensure_running(self.home)
        self.assertEqual(ready["service"], SERVICE)
        self.assertTrue(stop_worker(self.home))
        self.assertFalse(stop_worker(self.home))

    def test_os_lock_prevents_import_into_running_installation(self):
        store = self.seed()
        with worker_lock(self.home) as acquired:
            self.assertTrue(acquired)
            # An independent file handle is refused by the same OS lock.
            with worker_lock(self.home) as duplicate:
                self.assertFalse(duplicate)
            with self.assertRaises(ValueError):
                import_data(self.home, store.directory)
        self.assertEqual(Store(store.directory).get_bill("old-bill")["total_minor"], 4000)

    def test_import_keeps_customer_contact_identity_forecast_and_backups(self):
        store = self.seed()
        (store.directory / "forecast.json").write_text('{"test": "forecast preserved"}')
        (store.directory / "backups").mkdir()
        (store.directory / "backups" / "kept.zip").write_bytes(b"fixture backup")
        imported = import_data(self.home, store.directory)
        current = Store(imported)
        self.assertEqual(current.metadata()["store_id"], store.metadata()["store_id"])
        self.assertEqual(current.get_bill("old-bill")["customer_phone"], "919000000000")
        self.assertEqual(current.rows("SELECT stock FROM products")[0]["stock"], 23)
        self.assertEqual((imported / "forecast.json").read_text(), (store.directory / "forecast.json").read_text())
        self.assertEqual((imported / "backups" / "kept.zip").read_bytes(), b"fixture backup")
        self.assertEqual(Store(self.source).rows("SELECT stock FROM products")[0]["stock"], 23)

    def test_import_reads_committed_wal_and_never_overwrites_installed_data(self):
        store = self.seed()
        with store.connect() as connection:
            connection.execute("PRAGMA wal_autocheckpoint=0")
            connection.execute("UPDATE products SET stock=19")
            connection.commit()
            self.assertTrue((self.source / "retailpulse.sqlite3-wal").exists())
            import_data(self.home, self.source)
        destination = Store(self.home / "data")
        self.assertEqual(destination.rows("SELECT stock FROM products")[0]["stock"], 19)
        with self.assertRaises(ValueError):
            import_data(self.home, self.source)
        self.assertEqual(destination.get_bill("old-bill")["customer_phone"], "919000000000")

    def test_invalid_and_future_database_imports_leave_destination_empty(self):
        self.source.mkdir()
        with self.assertRaises(ValueError):
            import_data(self.home, self.source)
        (self.source / "retailpulse.sqlite3").write_bytes(b"not a SQLite database")
        with self.assertRaises(sqlite3.DatabaseError):
            import_data(self.home, self.source)
        (self.source / "retailpulse.sqlite3").unlink()
        with closing(sqlite3.connect(self.source / "retailpulse.sqlite3")) as connection:
            connection.execute("PRAGMA user_version=99")
        with self.assertRaises(ValueError):
            import_data(self.home, self.source)
        self.assertFalse((self.home / "data" / "retailpulse.sqlite3").exists())

    def test_browser_app_mode_receives_argument_list_and_can_fall_back(self):
        url = "http://127.0.0.1:18741/"
        with patch("retailpulse.desktop.browser_executable", return_value=Path("C:/Program Files/Chrome/chrome.exe")), patch("retailpulse.desktop.subprocess.Popen") as popen:
            open_window(url)
            args, options = popen.call_args
            self.assertIn("--app=" + url, args[0])
            self.assertFalse(options.get("shell", False))
        with patch("retailpulse.desktop.browser_executable", return_value=None), patch("retailpulse.desktop.webbrowser.open", return_value=True) as browser:
            open_window(url)
            browser.assert_called_once_with(url)
        with patch("retailpulse.desktop.browser_executable", return_value=None), patch("retailpulse.desktop.webbrowser.open", return_value=False):
            with self.assertRaises(RuntimeError):
                open_window(url)

    def test_explicit_home_does_not_depend_on_current_project_directory(self):
        self.assertEqual(app_home(str(self.home)), self.home.resolve())
        with patch.dict(os.environ, {"SATYA_SHOP_HOME": str(self.home)}):
            self.assertEqual(app_home(), self.home.resolve())


if __name__ == "__main__":
    unittest.main()
