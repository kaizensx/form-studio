"""The bridge between the Qt Quick interface and FORM's engine.

The engine API runs inside this process on a loopback port that only this app talks to. Requests are made
on worker threads, so the interface never waits on the CAD kernel or the slicer.
"""
from __future__ import annotations

import base64
import http.client
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import Property, QObject, QRunnable, QStandardPaths, QThreadPool, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtQml import QJSValue


# a conversation attachment: the engine takes the file by its path (cloned or linked into the conversation), so a
# 500 MB scan is never read by the app or sent over the loopback socket
_ATTACH = re.compile(r"/conversations/[0-9a-f]{12}/attach(\?.*)?")
# a game asset build or export: Blender may bake for up to form/game/pipeline.py's TIMEOUT_S, so the request waits
# longer than that (the pipeline's watchdog stops Blender first, and its error is what the sheet shows)
_GAME_BUILD = re.compile(r"/projects/[^/?]+/game")
HTTP_TIMEOUT_S = 900.0


def _game_timeout() -> float:
    try:
        from ..game.pipeline import TIMEOUT_S
    except Exception:                         # noqa: BLE001 - the game pipeline missing never breaks a request
        TIMEOUT_S = 1800.0
    return float(TIMEOUT_S) + 120.0


def _flight_key(method: str, path: str, body) -> str | None:
    """Requests that must never run twice at once (single flight): a game asset build or export of one project with
    the same options. A second identical request while the first runs waits for its answer instead of starting a
    second Blender."""
    if method != "POST" or not _GAME_BUILD.fullmatch(path):
        return None
    try:
        return method + " " + path + " " + json.dumps(body if body is not None else {}, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return method + " " + path


def blender_children(pid: int | None = None) -> list[int]:
    """Process ids of Blender processes this process started (direct children whose command names blender). The
    game pipeline starts Blender in its own session (form/game/pipeline.py), so quitting the app does not stop it."""
    pid = os.getpid() if pid is None else pid
    out = []
    try:
        if os.name == "nt":
            r = subprocess.run(["wmic", "process", "where", f"ParentProcessId={pid}", "get", "ProcessId,CommandLine",
                                "/format:csv"], capture_output=True, text=True, timeout=10)
            for line in r.stdout.splitlines():
                parts = line.strip().split(",")
                if len(parts) >= 3 and "blender" in ",".join(parts[1:-1]).lower() and parts[-1].isdigit():
                    out.append(int(parts[-1]))
            return out
        r = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,command="], capture_output=True, text=True, timeout=10)
        for line in r.stdout.splitlines():
            f = line.split(None, 2)
            if len(f) == 3 and f[1] == str(pid) and "blender" in f[2].lower() and f[0].isdigit():
                out.append(int(f[0]))
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return out


def kill_blender_children() -> list[int]:
    """Stop every Blender this app started, with its process group (Blender's own children too). Returns the ids."""
    import signal
    killed = []
    for p in blender_children():
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(p)], capture_output=True, timeout=10)
            else:
                try:
                    os.killpg(p, signal.SIGKILL)       # the pipeline makes Blender a session (and group) leader
                except OSError:
                    os.kill(p, signal.SIGKILL)
            killed.append(p)
        except (OSError, subprocess.SubprocessError):
            pass
    return killed


class _Call(QRunnable):
    def __init__(self, bridge: "Bridge", rid: int, method: str, path: str, body, raw: bytes | None = None,
                 raw_file: str | None = None, flight: str | None = None):
        super().__init__()
        self.b, self.rid, self.method, self.path, self.body, self.raw = bridge, rid, method, path, body, raw
        self.raw_file = raw_file              # a local file streamed as the body, read on this worker thread
        self.flight = flight                  # single flight: every request id waiting on this one gets its reply
        self.timeout = _game_timeout() if _GAME_BUILD.fullmatch(path) and method == "POST" else HTTP_TIMEOUT_S

    def emit(self, ok: bool, obj):
        for rid in self.b._land(self.flight, self.rid):
            self.b.reply.emit(rid, ok, obj)

    def run(self):
        f = None
        try:
            conn = http.client.HTTPConnection(self.b.host, self.b.port, timeout=self.timeout)
            headers, data = {}, None
            if self.method == "POST":
                if self.raw_file is not None:
                    try:
                        f = open(self.raw_file, "rb")
                    except OSError as e:
                        self.emit(False, {"message": f"Could not read that file: {e}", "status": 0})
                        return
                    data = f
                    headers = {"Content-Type": "application/octet-stream", "Content-Length": str(os.fstat(f.fileno()).st_size)}
                elif self.raw is not None:
                    data, headers = self.raw, {"Content-Type": "application/octet-stream"}
                else:
                    data, headers = json.dumps(self.body if self.body is not None else {}).encode(), {"Content-Type": "application/json"}
            try:
                conn.request(self.method, "/api" + self.path, body=data, headers=headers)
                res = conn.getresponse()
                payload = res.read()
            except (ConnectionError, http.client.RemoteDisconnected):
                # a read asked while the engine's accept queue was full: ask once more (never a POST: it may have run)
                if self.method != "GET":
                    raise
                conn.close()
                time.sleep(0.2)
                conn = http.client.HTTPConnection(self.b.host, self.b.port, timeout=self.timeout)
                conn.request("GET", "/api" + self.path)
                res = conn.getresponse()
                payload = res.read()
            conn.close()
            try:
                obj = json.loads(payload)
            except ValueError:
                obj = {"error": {"message": f"Unexpected response ({res.status})"}}
            if res.status >= 400 or (isinstance(obj, dict) and obj.get("error")):
                err = obj.get("error") if isinstance(obj, dict) else None
                self.emit(False, {**(err or {"message": res.reason}), "status": res.status})
            else:
                self.emit(True, obj)
        except RuntimeError:        # the app is quitting and the bridge is gone; nobody is waiting for this reply
            return
        except Exception as e:      # the engine thread died or the socket closed
            try:
                self.emit(False, {"message": "The Form Studio engine is not answering.",
                                                     "hint": f"Restart Form Studio. Your projects are saved on disk. ({e})", "status": 0})
            except RuntimeError:
                pass
        finally:
            if f is not None:
                f.close()


def _solid_glass() -> bool:
    """True when panes should be solid instead of blurred glass: the OS "reduce transparency" preference, Low Power
    Mode, a software renderer, or FORM_GLASS=solid/blur to force it. Never raises."""
    import os
    env = os.environ.get("FORM_GLASS", "").strip().lower()
    if env:
        return env in ("solid", "0", "off", "no", "false")
    if os.environ.get("QT_QUICK_BACKEND", "").lower() == "software":
        return True
    try:
        if sys.platform == "darwin":
            out = subprocess.run(["defaults", "read", "com.apple.universalaccess", "reduceTransparency"],
                                 capture_output=True, text=True, timeout=2).stdout.strip()
            if out == "1":
                return True
            out = subprocess.run(["pmset", "-g"], capture_output=True, text=True, timeout=2).stdout
            for line in out.splitlines():
                if line.strip().startswith("lowpowermode"):
                    return line.split()[-1] == "1"
            return False
        if sys.platform.startswith("win"):
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
                return winreg.QueryValueEx(k, "EnableTransparency")[0] == 0
    except Exception:
        return False
    return False


def _reduced_motion() -> bool:
    """The OS "reduce motion" preference, or FORM_REDUCED_MOTION=1/0 to force it. Never raises."""
    import os
    env = os.environ.get("FORM_REDUCED_MOTION", "").strip().lower()
    if env:
        return env not in ("0", "false", "no", "off")
    try:
        if sys.platform == "darwin":
            out = subprocess.run(["defaults", "read", "com.apple.universalaccess", "reduceMotion"],
                                 capture_output=True, text=True, timeout=2).stdout.strip()
            return out == "1"
        if sys.platform.startswith("win"):
            import ctypes
            on = ctypes.c_int(1)
            ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(on), 0)   # SPI_GETCLIENTAREAANIMATION
            return on.value == 0
        out = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "enable-animations"],
                             capture_output=True, text=True, timeout=2).stdout.strip()
        return out == "false"
    except Exception:
        return False


class Bridge(QObject):
    reply = Signal(int, bool, "QVariant")

    def __init__(self, host: str, port: int, data_dir: str, version: str, parent=None):
        super().__init__(parent)
        self.host, self.port, self._data, self._version = host, port, data_dir, version
        self.pool = QThreadPool.globalInstance()
        self.pool.setMaxThreadCount(max(8, self.pool.maxThreadCount()))
        import threading
        self._flights: dict[str, list[int]] = {}      # single-flight key -> request ids waiting on it
        self._flock = threading.Lock()
        app = QGuiApplication.instance()
        if app is not None:                            # quitting stops the Blender bakes this app started
            app.aboutToQuit.connect(self.stopChildren)

    @Slot(result=int)
    def stopChildren(self) -> int:
        """Stop the Blender processes this app started (a bake in progress when the app quits). Returns how many."""
        return len(kill_blender_children())

    def _join(self, key: str | None, rid: int) -> bool:
        """True when this request starts its flight (or has none); False when it joined one already running."""
        if key is None:
            return True
        with self._flock:
            if key in self._flights:
                self._flights[key].append(rid)
                return False
            self._flights[key] = [rid]
            return True

    def _land(self, key: str | None, rid: int) -> list[int]:
        """The request ids a finished request answers: its own, or everyone in its flight."""
        if key is None:
            return [rid]
        with self._flock:
            return self._flights.pop(key, None) or [rid]

    @Slot(QObject, float, result=bool)
    @Slot(QObject, float, float, result=bool)
    def centerWindowButtons(self, window, bar_height: float, left: float = 0.0) -> bool:
        """macOS: the close, minimise and zoom buttons centred on the top bar (form/app/macwin.py)."""
        if sys.platform != "darwin" or window is None:
            return False
        from . import macwin
        try:
            return macwin.center_buttons(int(window.winId()), float(bar_height), float(left))
        except Exception:
            return False

    # -- interaction tests (form/app/uitest.py): no native dialogs, nothing opened outside the app -------------
    def _test_dir(self) -> str:
        import os
        return os.environ.get("FORM_UITEST_FILES", "") if getattr(self, "under_test", False) else ""

    testDir = Property(str, _test_dir, constant=True)

    @Slot(result=str)
    def testPick(self) -> str:
        """The file the test queued for the next open dialog ("" = none: a save dialog gets a path in testDir)."""
        p, self._test_pick = getattr(self, "_test_pick", ""), ""
        return p

    @Slot(str, result=QUrl)
    def fileUrl(self, path: str) -> QUrl:
        return QUrl.fromLocalFile(path)

    def _outside(self, what: str, arg: str) -> bool:
        """True (and recorded) when a test is running: Finder, the browser and other apps stay closed."""
        if not getattr(self, "under_test", False):
            return False
        self.__dict__.setdefault("outside", []).append((what, arg))
        return True

    # -- engine -------------------------------------------------------------
    @Slot(int, str, str, "QVariant")
    def request(self, rid: int, method: str, path: str, body):
        if isinstance(body, QJSValue):
            body = body.toVariant()
        key = _flight_key(method, path, body)
        if self._join(key, rid):
            self.pool.start(_Call(self, rid, method, path, body, flight=key))

    @Slot(int, str, QUrl)
    def upload(self, rid: int, path: str, file: QUrl):
        """POST a local file (attachments, project archives). Nothing is read on the interface thread: a conversation
        attachment is handed to the engine by its path, anything else is streamed from a worker thread."""
        local = file.toLocalFile()
        if _ATTACH.fullmatch(path):
            from urllib.parse import parse_qs, urlsplit
            name = (parse_qs(urlsplit(path).query).get("name") or [""])[0]
            self.pool.start(_Call(self, rid, "POST", path.split("?", 1)[0], {"paths": [local], "names": [name]}))
            return
        self.pool.start(_Call(self, rid, "POST", path, None, raw_file=local))

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

    # -- app shell: reduced motion, read once at start ----------------------
    def _reduced(self) -> bool:
        if not hasattr(self, "_rm"):
            self._rm = _reduced_motion()
        return self._rm

    reducedMotion = Property(bool, _reduced, constant=True)

    # -- glass: blurred panes over the 3D view, unless the system asks for solid ones or the machine saves power ----
    def _solid(self) -> bool:
        if not hasattr(self, "_sg"):
            self._sg = _solid_glass()
        return self._sg

    solidGlass = Property(bool, _solid, constant=True)

    # -- appearance: what the system asks for (it can change while the app runs), and a one-run override ------------
    def _system_dark(self) -> bool:
        try:
            from PySide6.QtCore import Qt
            from PySide6.QtGui import QGuiApplication
            return QGuiApplication.styleHints().colorScheme() != Qt.ColorScheme.Light
        except Exception:
            return True

    systemDarkChanged = Signal()
    systemDark = Property(bool, _system_dark, notify=systemDarkChanged)

    def _appearance_override(self) -> str:
        v = os.environ.get("FORM_APPEARANCE", "").strip().lower()
        return v if v in ("light", "dark") else ""

    appearanceOverride = Property(str, _appearance_override, constant=True)

    def _ffmpeg(self) -> bool:                  # MP4 turntables need it (form/animate.py)
        from ..animate import ffmpeg
        return ffmpeg() is not None

    hasFfmpeg = Property(bool, _ffmpeg, constant=True)
    underTest = Property(bool, lambda self: bool(getattr(self, "under_test", False)), constant=True)   # interaction tests: no splash

    def _qt(self) -> str:
        import PySide6
        return PySide6.__version__

    qtVersion = Property(str, _qt, constant=True)
    pythonVersion = Property(str, lambda self: sys.version.split()[0], constant=True)

    @Slot(str, result=str)
    def licence(self, name: str) -> str:
        """The licence text of a bundled font ("Geist", "InstrumentSans", "GeistMono", "lucide") or of FORM itself ("FORM")."""
        here = Path(__file__).resolve().parent
        if name == "FORM":
            for p in (here.parent.parent / "LICENSE", here / "assets" / "LICENSE"):
                if p.exists():
                    return p.read_text(encoding="utf-8", errors="replace")
            return "MIT License. The full text is in the LICENSE file of the form-studio repository."
        if name in ("Geist", "InstrumentSans", "GeistMono", "lucide"):
            p = here / "assets" / "fonts" / f"{name}-LICENSE.txt"
            if p.exists():
                return p.read_text(encoding="utf-8", errors="replace")
        return ""

    @Slot(result=str)
    def showpiece(self) -> str:
        """Home's first-day part: the view of a real build (a sensor enclosure, 13 features, made by the kernel from
        its recipe) kept as a file, so an empty Home shows what a design looks like without creating a project.
        "" when the file is missing."""
        p = Path(__file__).resolve().parent / "assets" / "showpiece.json"
        try:
            return p.read_text(encoding="utf-8")
        except OSError:
            return ""

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
        if self._outside("reveal", p):
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", p])
        elif sys.platform.startswith("win"):
            subprocess.Popen(["explorer", "/select,", str(Path(p))])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(p).parent)))

    @Slot(str)
    def openProjectFolder(self, rel: str):
        """A folder inside the projects folder (a design, a release), opened in Finder / Explorer."""
        base = Path(self._data).resolve()
        p = (base / rel).resolve()
        if base not in p.parents or not p.is_dir() or self._outside("folder", str(p)):
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    @Slot()
    def openDataFolder(self):
        if self._outside("folder", self._data):
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(self._data))

    @Slot(str)
    def openLink(self, url: str):
        if self._outside("link", url):
            return
        if url.startswith(("https://", "http://")):
            QDesktopServices.openUrl(QUrl(url))

    @Slot(str, "QVariant", result=str)
    def markdown(self, text: str, style) -> str:
        """Markdown → the rich text the interface draws (see markdown.py): lists on the app's own grid."""
        from .markdown import to_html
        if hasattr(style, "toVariant"):
            style = style.toVariant()
        return to_html(text, style if isinstance(style, dict) else None)

    @Slot(str)
    def copy(self, text: str):
        QGuiApplication.clipboard().setText(text)

    @Slot(result=str)
    def clipboardText(self) -> str:
        return QGuiApplication.clipboard().text() or ""

    @Slot(result=QUrl)
    def clipboardImage(self) -> QUrl:
        """A picture on the clipboard (a screenshot, a copied photo), saved as a PNG to attach; empty when there is none."""
        img = QGuiApplication.clipboard().image()
        if img.isNull():
            return QUrl()
        f = Path(tempfile.mkdtemp(prefix="form-paste-")) / "pasted.png"
        return QUrl.fromLocalFile(str(f)) if img.save(str(f), "PNG") else QUrl()

    @Slot(str, result=str)
    def tempFile(self, name: str) -> str:
        """A path in a fresh temporary folder (a sketch's picture is written there before it is attached)."""
        safe = "".join(c for c in name if c.isalnum() or c in "-_.") or "file"
        return str(Path(tempfile.mkdtemp(prefix="form-tmp-")) / safe)

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
