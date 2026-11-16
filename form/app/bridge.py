"""The bridge between the Qt Quick interface and FORM's engine.

The engine API runs inside this process on a loopback port that only this app talks to. Requests are made
on worker threads, so the interface never waits on the CAD kernel or the slicer.
"""
from __future__ import annotations

import base64
import http.client
import json
import mimetypes
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Property, QObject, QRunnable, QStandardPaths, QThreadPool, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtQml import QJSValue


class _Call(QRunnable):
    def __init__(self, bridge: "Bridge", rid: int, method: str, path: str, body, raw: bytes | None = None):
        super().__init__()
        self.b, self.rid, self.method, self.path, self.body, self.raw = bridge, rid, method, path, body, raw

    def run(self):
        try:
            conn = http.client.HTTPConnection(self.b.host, self.b.port, timeout=900)
            headers, data = {}, None
            if self.method == "POST":
                if self.raw is not None:
                    data, headers = self.raw, {"Content-Type": "application/octet-stream"}
                else:
                    data, headers = json.dumps(self.body if self.body is not None else {}).encode(), {"Content-Type": "application/json"}
            conn.request(self.method, "/api" + self.path, body=data, headers=headers)
            res = conn.getresponse()
            payload = res.read()
            conn.close()
            try:
                obj = json.loads(payload)
            except ValueError:
                obj = {"error": {"message": f"Unexpected response ({res.status})"}}
            if res.status >= 400 or (isinstance(obj, dict) and obj.get("error")):
                err = obj.get("error") if isinstance(obj, dict) else None
                self.b.reply.emit(self.rid, False, {**(err or {"message": res.reason}), "status": res.status})
            else:
                self.b.reply.emit(self.rid, True, obj)
        except Exception as e:      # the engine thread died or the socket closed
            self.b.reply.emit(self.rid, False, {"message": "The FORM engine is not answering.",
                                                 "hint": f"Restart FORM. Your projects are saved on disk. ({e})", "status": 0})


class Bridge(QObject):
    reply = Signal(int, bool, "QVariant")

    def __init__(self, host: str, port: int, data_dir: str, version: str, parent=None):
        super().__init__(parent)
        self.host, self.port, self._data, self._version = host, port, data_dir, version
        self.pool = QThreadPool.globalInstance()
        self.pool.setMaxThreadCount(max(8, self.pool.maxThreadCount()))

    # -- engine -------------------------------------------------------------
    @Slot(int, str, str, "QVariant")
    def request(self, rid: int, method: str, path: str, body):
        if isinstance(body, QJSValue):
            body = body.toVariant()
        self.pool.start(_Call(self, rid, method, path, body))

    @Slot(int, str, QUrl)
    def upload(self, rid: int, path: str, file: QUrl):
        """POST a local file's bytes (project archives)."""
        try:
            raw = Path(file.toLocalFile()).read_bytes()
        except OSError as e:
            self.reply.emit(rid, False, {"message": f"Could not read that file: {e}", "status": 0})
            return
        self.pool.start(_Call(self, rid, "POST", path, None, raw))

    @Slot(QUrl, result=str)
    def dataUrl(self, file: QUrl) -> str:
        p = Path(file.toLocalFile())
        try:
            kind = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            return f"data:{kind};base64," + base64.b64encode(p.read_bytes()).decode()
        except OSError:
            return ""

    def _base(self) -> str:
        return f"http://{self.host}:{self.port}"

    baseUrl = Property(str, _base, constant=True)
    version = Property(str, lambda self: self._version, constant=True)
    dataDir = Property(str, lambda self: self._data, constant=True)

    def _short(self) -> str:
        home = str(Path.home())
        return "~" + self._data[len(home):] if self._data.startswith(home) else self._data

    dataDirShort = Property(str, _short, constant=True)
    platform = Property(str, lambda self: sys.platform, constant=True)

    # -- desktop integration -------------------------------------------------
    @Slot(str, QUrl, result=bool)
    def save(self, api_path: str, dest: QUrl) -> bool:
        """Download an engine file to a place the user chose in the native save dialog."""
        try:
            conn = http.client.HTTPConnection(self.host, self.port, timeout=120)
            conn.request("GET", "/api" + api_path)
            res = conn.getresponse()
            data = res.read()
            conn.close()
            if res.status != 200:
                return False
            Path(dest.toLocalFile()).write_bytes(data)
            return True
        except OSError:
            return False

    @Slot(result=QUrl)
    def downloads(self) -> QUrl:
        return QUrl.fromLocalFile(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation))

    @Slot(QUrl)
    def reveal(self, file: QUrl):
        p = file.toLocalFile()
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", p])
        elif sys.platform.startswith("win"):
            subprocess.Popen(["explorer", "/select,", str(Path(p))])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(p).parent)))

    @Slot()
    def openDataFolder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(self._data))

    @Slot(str)
    def openLink(self, url: str):
        if url.startswith(("https://", "http://")):
            QDesktopServices.openUrl(QUrl(url))

    @Slot(str)
    def copy(self, text: str):
        QGuiApplication.clipboard().setText(text)

    @Slot(str, result=bool)
    def copyImage(self, api_path: str) -> bool:
        """Put an engine image (the share card) on the clipboard."""
        from PySide6.QtGui import QImage
        try:
            conn = http.client.HTTPConnection(self.host, self.port, timeout=120)
            conn.request("GET", "/api" + api_path)
            res = conn.getresponse()
            data = res.read()
            conn.close()
        except OSError:
            return False
        img = QImage.fromData(data)
        if res.status != 200 or img.isNull():
            return False
        QGuiApplication.clipboard().setImage(img)
        return True

    @Slot(result=bool)
    def hasClaude(self) -> bool:
        return bool(shutil.which("claude"))
