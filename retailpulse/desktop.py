"""Launch the local shop independently of an editor; no third-party desktop runtime."""
from contextlib import contextmanager, closing
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler
from wsgiref.simple_server import make_server, WSGIRequestHandler
import argparse
import hashlib
import hmac
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import webbrowser
from . import __version__

SERVICE = "satya-shop-desktop"
CONTROL = "/_satya_desktop/"
DEFAULT_PORT = 18741
_children = []
_children_lock = threading.Lock()


def remember_process(process):
    # Retain our process handles until they exit; none are terminated by the launcher.
    with _children_lock:
        _children[:] = [child for child in _children if child.poll() is None]
        _children.append(process)
    return process


def app_home(value=None):
    if value or os.environ.get("SATYA_SHOP_HOME"):
        return Path(value or os.environ["SATYA_SHOP_HOME"]).expanduser().resolve()
    if os.name == "nt":
        location = os.environ.get("LOCALAPPDATA")
        if not location:
            raise ValueError("Windows could not find your local app folder. Try signing in again.")
        return Path(location) / "SatyaShop"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "SatyaShop"


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + secrets.token_hex(6) + ".tmp")
    try:
        with open(temporary, "x", encoding="utf-8") as handle:
            if os.name != "nt":
                os.chmod(temporary, 0o600)
            json.dump(value, handle)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def worker_lock(home):
    """An OS-held lock releases after a crash; never trust or kill a recycled PID."""
    path = Path(home) / "run" / "worker.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if not handle.tell():
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        locked = False
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError:
            pass
        try:
            yield locked
        finally:
            if locked:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def control_request(home, action="status", timeout=1):
    """Only contact a verified loopback worker for this installation."""
    try:
        record = json.loads((Path(home) / "run" / "server.json").read_text(encoding="utf-8"))
        port, key = record["port"], record["key"]
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            return None
        if not isinstance(key, str) or len(key) != 64:
            return None
        expected = hashlib.sha256(str(Path(home).resolve()).encode()).hexdigest()
        if record.get("home_id") != expected or record.get("service") != SERVICE:
            return None
        url = f"http://127.0.0.1:{port}{CONTROL}{action}"
        request = Request(url, headers={"X-Satya-Launcher-Key": key},
                          data=b"" if action == "stop" else None)
        opener = build_opener(ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=timeout) as response:
            result = json.loads(response.read(8192))
        if result.get("service") != SERVICE or result.get("instance") != record["instance"]:
            return None
        return {**record, "url": f"http://127.0.0.1:{port}/", "status": result}
    except (OSError, ValueError, KeyError, TypeError):
        return None


class DesktopController:
    def __init__(self, application, key, instance):
        self.application, self.key, self.instance = application, key, instance
        self.server = None

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "")
        if not path.startswith(CONTROL):
            return self.application(environ, start_response)
        status = "200 OK"
        if not hmac.compare_digest(environ.get("HTTP_X_SATYA_LAUNCHER_KEY", ""), self.key):
            status, result = "403 Forbidden", {"error": "This action is available from the desktop launcher."}
        elif path == CONTROL + "status" and environ.get("REQUEST_METHOD") == "GET":
            result = {"service": SERVICE, "instance": self.instance, "version": __version__}
        elif path == CONTROL + "stop" and environ.get("REQUEST_METHOD") == "POST":
            if self.application.training:
                status, result = "409 Conflict", {"error": "Wait for forecast training to finish, then quit again."}
            else:
                result = {"service": SERVICE, "instance": self.instance, "stopping": True}
                threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            status, result = "404 Not Found", {"error": "Unknown desktop action."}
        body = json.dumps(result).encode()
        start_response(status, [("Content-Type", "application/json"), ("Content-Length", str(len(body))),
                                ("Cache-Control", "no-store")])
        return [body]


class QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):
        pass


def run_worker(home):
    from .web import Application, ThreadedServer
    home = Path(home).resolve()
    home.mkdir(parents=True, exist_ok=True)
    with worker_lock(home) as locked:
        if not locked:
            return 0
        key, instance = secrets.token_hex(32), secrets.token_hex(16)
        app = Application(home / "data", desktop=True)
        controller = DesktopController(app, key, instance)
        # Wait for in-flight requests before the final backup and process exit.
        class DesktopServer(ThreadedServer):
            daemon_threads = False
        port_file = home / "run" / "last-port.json"
        try:
            previous = json.loads(port_file.read_text())["port"]
        except (OSError, ValueError, KeyError, TypeError):
            previous = DEFAULT_PORT
        ports = [previous] if isinstance(previous, int) and not isinstance(previous, bool) and 1024 <= previous <= 65535 else []
        ports.extend(p for p in range(DEFAULT_PORT, DEFAULT_PORT + 10) if p not in ports)
        ports.append(0)
        server = None
        for port in ports:
            try:
                server = make_server("127.0.0.1", port, controller, server_class=DesktopServer, handler_class=QuietHandler)
                break
            except OSError as error:
                import errno
                if error.errno not in (errno.EADDRINUSE, 10048):
                    raise
        if server is None:
            raise RuntimeError("Could not open a local shop connection.")
        controller.server = server
        marker = home / "run" / "server.json"
        record = {"service": SERVICE, "instance": instance, "key": key, "pid": os.getpid(),
                  "home_id": hashlib.sha256(str(home).encode()).hexdigest(), "port": server.server_port}
        try:
            with server:
                app.backups.start()
                atomic_json(port_file, {"port": server.server_port})
                atomic_json(marker, record)
                server.serve_forever(poll_interval=0.1)
        finally:
            app.backups.stop()
            try:
                app.backups.create("auto")
            except Exception:
                pass  # Backup failures also remain in the local log/dashboard.
            try:
                if json.loads(marker.read_text()).get("instance") == instance:
                    marker.unlink()
            except (OSError, ValueError):
                pass
    return 0


def spawn_worker(home):
    executable = Path(sys.executable)
    if os.name == "nt" and executable.with_name("pythonw.exe").exists():
        executable = executable.with_name("pythonw.exe")
    args = [str(executable), "-m", "retailpulse.desktop", "--home", str(home), "--worker"]
    options = {"cwd": str(Path(__file__).resolve().parent.parent), "stdin": subprocess.DEVNULL,
               "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True}
    if os.name == "nt":
        options["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    return remember_process(subprocess.Popen(args, **options))


def ensure_running(home, timeout=35):
    current = control_request(home)
    if current:
        return current
    process = spawn_worker(home)
    last_spawn = time.monotonic()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = control_request(home, timeout=0.3)
        if current:
            return current
        if process.poll() not in (None, 0):
            raise RuntimeError("Satya Shop could not start. Open logs/desktop.log in the installed shop folder for details.")
        if process.poll() == 0 and time.monotonic() - last_spawn >= 1:
            # Another launcher or a finishing shutdown held the lock. Retry after it releases.
            process = spawn_worker(home)
            last_spawn = time.monotonic()
        time.sleep(0.1)
    raise RuntimeError("Your shop is taking too long to open. Try its icon again, or check logs/desktop.log.")


def stop_worker(home, timeout=20):
    current = control_request(home)
    if not current:
        return False
    if not control_request(home, "stop", timeout=2):
        raise RuntimeError("Could not quit the shop. Finish forecast training and try again.")
    deadline = time.monotonic() + timeout
    marker = Path(home) / "run" / "server.json"
    while time.monotonic() < deadline:
        if not marker.exists():
            with _children_lock:
                for process in _children:
                    if process.pid == current["pid"]:
                        try:
                            process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            pass
                _children[:] = [child for child in _children if child.poll() is None]
            return True
        time.sleep(0.1)
    raise RuntimeError("The shop is still finishing its backup. Wait and try again.")


def browser_executable():
    if os.name != "nt":
        return None
    for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"), os.environ.get("LOCALAPPDATA")):
        if not base:
            continue
        for relative in ("Microsoft/Edge/Application/msedge.exe", "Google/Chrome/Application/chrome.exe"):
            path = Path(base) / relative
            if path.is_file():
                return path
    return None


def open_window(url):
    browser = browser_executable()
    if browser:
        try:
            subprocess.Popen([str(browser), "--app=" + url, "--window-size=1360,920"],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            pass
    if not webbrowser.open(url):
        raise RuntimeError("Your shop is running, but no browser opened. Open " + url + " in Chrome or Edge.")


def import_data(home, source):
    """Import a consistent SQLite snapshot; never overwrite existing installed records."""
    from .store import Store
    home, source = Path(home).resolve(), Path(source).resolve()
    original, target = source / "retailpulse.sqlite3", home / "data"
    if not original.is_file():
        raise ValueError("Choose the data folder that contains retailpulse.sqlite3, such as your old shop-data folder.")
    home.mkdir(parents=True, exist_ok=True)
    with worker_lock(home) as locked:
        if not locked:
            raise ValueError("Quit the installed Satya Shop before importing records.")
        if target.exists() and any(target.iterdir()):
            raise ValueError("This installed shop already has records. They were kept; an import will not overwrite them.")
        with TemporaryDirectory(prefix="import-", dir=home) as work:
            staged = Path(work) / "data"
            staged.mkdir()
            with closing(sqlite3.connect(original.as_uri() + "?mode=ro", uri=True, timeout=15)) as old, closing(sqlite3.connect(staged / "retailpulse.sqlite3")) as new:
                old.backup(new)
                if new.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("The source database did not pass its integrity check. Your original folder was kept.")
            for item in source.iterdir():
                if item.name in ("retailpulse.sqlite3", "retailpulse.sqlite3-wal", "retailpulse.sqlite3-shm", "retailpulse.sqlite3-journal"):
                    continue
                if item.is_dir():
                    shutil.copytree(item, staged / item.name)
                elif item.is_file():
                    shutil.copy2(item, staged / item.name)
            Store(staged)  # Validate/migrate the copy, never the original database.
            if target.exists():
                target.rmdir()  # Only the verified empty destination above.
            os.replace(staged, target)
        atomic_json(home / "import-info.json", {"source": str(source), "imported_at": time.time()})
    return target


def choose_data(home, candidate=None):
    if (Path(home) / "data" / "retailpulse.sqlite3").exists():
        return
    if candidate and (Path(candidate) / "retailpulse.sqlite3").exists():
        import_data(home, candidate)
        return
    import tkinter as tk
    from tkinter import filedialog, messagebox
    root = tk.Tk()
    root.withdraw()
    try:
        answer = messagebox.askyesnocancel("Satya Shop — your records", "Do you already have shop records?\n\nYes: select your old shop-data folder.\nNo: start a new empty shop.\nCancel: leave setup unfinished.", parent=root)
        if answer is None:
            raise ValueError("Setup was cancelled. Run the installer again when you are ready.")
        if answer:
            selected = filedialog.askdirectory(title="Select your existing shop-data folder", parent=root, mustexist=True)
            if not selected:
                raise ValueError("No data folder was selected. Your original records were kept.")
            import_data(home, selected)
    finally:
        root.destroy()


def notice(message, error=False):
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, str(message), "Satya Shop", 0x10 if error else 0x40)
    elif sys.stderr:
        print(message, file=sys.stderr)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Satya Shop desktop launcher")
    parser.add_argument("--home")
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--choose-data", action="store_true")
    parser.add_argument("--source-data")
    parser.add_argument("--import-data")
    args = parser.parse_args(argv)
    home = app_home(args.home)
    log = None
    try:
        if args.worker:
            directory = home / "logs"
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / "desktop.log"
            if path.exists() and path.stat().st_size > 3_000_000:
                os.replace(path, directory / "desktop-previous.log")
            log = open(path, "a", encoding="utf-8", buffering=1)
            sys.stdout = sys.stderr = log
            return run_worker(home)
        if args.import_data:
            import_data(home, args.import_data)
        elif args.choose_data:
            choose_data(home, args.source_data)
        elif args.stop:
            stopped = stop_worker(home)
            if not args.quiet:
                notice("Satya Shop has quit. Click its desktop icon to open it again." if stopped else "Satya Shop is already stopped.")
        else:
            ready = ensure_running(home)
            open_window(ready["url"])
        return 0
    except Exception as error:
        if args.worker:
            import traceback
            traceback.print_exc()
        else:
            notice(str(error), error=True)
        return 1
    finally:
        if log:
            log.flush()


if __name__ == "__main__":
    sys.exit(main())
