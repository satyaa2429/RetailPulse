"""Consistent SQLite backups, hourly scheduling, and restore into a new folder."""
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path
import json
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import uuid
from zipfile import ZipFile, ZIP_DEFLATED

BACKUP_NAME = re.compile(r"RetailPulse-(auto|manual)-\d{8}T\d{6}Z-[a-f0-9]{8}\.zip")


def list_backups(store):
    directory = store.directory / "backups"
    rows = []
    for file in directory.glob("*.zip"):
        if not BACKUP_NAME.fullmatch(file.name): continue
        try: stat = file.stat()
        except FileNotFoundError: continue
        rows.append({"filename":file.name,"size_bytes":stat.st_size,
                     "created_at":datetime.fromtimestamp(stat.st_mtime,timezone.utc).isoformat(),
                     "kind":"auto" if "-auto-" in file.name else "manual"})
    return sorted(rows,key=lambda r:r["created_at"],reverse=True)


def create_backup(store, kind="manual", retain_auto=48):
    if kind not in ("auto","manual"): raise ValueError("Unknown backup type.")
    directory = store.directory / "backups"
    directory.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc)
    name = f"RetailPulse-{kind}-{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}.zip"
    with tempfile.TemporaryDirectory(dir=directory) as work:
        snapshot = Path(work)/"retailpulse.sqlite3"
        with closing(sqlite3.connect(store.path,timeout=15)) as source, closing(sqlite3.connect(snapshot)) as target:
            source.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
                raise ValueError("Database integrity check failed; backup was not saved.")
            meta = {r[0]:json.loads(r[1]) for r in target.execute("SELECT key,value FROM metadata")}
        info = {"format":1,"created_at":now.isoformat(),"kind":kind,"shop_name":meta.get("shop_name",""),
                "mode":meta.get("mode","unconfigured"),"schema_version":5,
                "note":"Database is a consistent SQLite snapshot. Forecast is an advisory saved artifact."}
        temporary = Path(work)/name
        with ZipFile(temporary,"w",ZIP_DEFLATED) as archive:
            archive.write(snapshot,"retailpulse.sqlite3")
            archive.writestr("backup_info.json",json.dumps(info,indent=2))
            forecast = store.directory/"forecast.json"
            if forecast.exists(): archive.writestr("forecast.json",forecast.read_bytes())
        os.replace(temporary,directory/name)
    automatic = [r for r in list_backups(store) if r["kind"]=="auto"]
    for row in automatic[retain_auto:]: (directory/row["filename"]).unlink(missing_ok=True)
    return {"filename":name,"created_at":now.isoformat(),"size_bytes":(directory/name).stat().st_size,"kind":kind}


def restore_backup(filename, directory):
    """Never overwrite an existing database; validate before installing its bytes."""
    directory = Path(directory).resolve()
    if directory.exists() and any(directory.iterdir()): raise ValueError("Restore needs a new empty data folder.")
    directory.mkdir(parents=True,exist_ok=True)
    destination = directory/"retailpulse.sqlite3"
    if destination.exists(): raise ValueError("Restore needs a new data folder with no existing database.")
    with ZipFile(filename) as archive:
        names = archive.namelist()
        if len(names)!=len(set(names)) or not {"retailpulse.sqlite3","backup_info.json"}.issubset(names) or set(names)-{"retailpulse.sqlite3","backup_info.json","forecast.json"}:
            raise ValueError("This is not a RetailPulse backup.")
        for item in archive.infolist():
            limit = 200_000_000 if item.filename=="retailpulse.sqlite3" else 50_000_000 if item.filename=="forecast.json" else 1_000_000
            if item.file_size>limit: raise ValueError("Backup file is too large for this restore tool.")
        info = json.loads(archive.read("backup_info.json"))
        if not isinstance(info,dict) or info.get("format")!=1 or info.get("schema_version",0)>5: raise ValueError("Unsupported backup version.")
        forecast = None
        if "forecast.json" in names:
            forecast = archive.read("forecast.json")
            artifact = json.loads(forecast)
            if not isinstance(artifact,dict) or not isinstance(artifact.get("rows"),list): raise ValueError("Invalid forecast in backup.")
        with tempfile.TemporaryDirectory(dir=directory) as work:
            candidate = Path(work)/"retailpulse.sqlite3"
            with archive.open("retailpulse.sqlite3") as source, candidate.open("wb") as target:
                shutil.copyfileobj(source,target)
            with closing(sqlite3.connect(candidate)) as conn:
                if conn.execute("PRAGMA integrity_check").fetchone()[0]!="ok" or conn.execute("PRAGMA foreign_key_check").fetchone(): raise ValueError("Backup database validation failed.")
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not {"products","events","metadata","bills","bill_lines"}.issubset(tables): raise ValueError("Backup database is incomplete.")
            os.link(candidate,destination)  # Fails if another process created the target; never overwrites.
            if forecast is not None:
                temporary_forecast = Path(work)/"forecast.json"
                temporary_forecast.write_bytes(forecast)
                os.replace(temporary_forecast,directory/"forecast.json")
    return {"directory":str(directory),"restored_from":str(filename),"backup_created_at":info.get("created_at")}


class BackupManager:
    def __init__(self, store, interval_seconds=3600):
        self.store = store
        self.interval = interval_seconds
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.last_backup = None
        self.error = None
        self.enabled = False

    def create(self,kind="manual"):
        with self.lock:
            try:
                result = create_backup(self.store,kind)
                self.last_backup,self.error = result,None
                return result
            except Exception as error:
                self.error = str(error)
                raise

    def start(self):
        if self.enabled: return
        self.enabled = True
        threading.Thread(target=self._loop,daemon=True,name="retailpulse-backup").start()

    def _loop(self):
        while not self.stop_event.is_set():
            try: self.create("auto")
            except Exception: pass  # The dashboard exposes the failure and manual retry.
            if self.stop_event.wait(self.interval): break

    def stop(self):
        self.stop_event.set()

    def status(self):
        return {"enabled":self.enabled,"interval_minutes":self.interval/60,
                "last_backup":self.last_backup,"error":self.error,"files":list_backups(self.store)[:20]}
