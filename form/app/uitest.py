"""Interaction tests for the desktop app: the real window, driven with real synthetic input events.

    python -m form.app --uitest tests/journeys/first_run.py            # runs run(ui) in that file
    python -m form.app --uitest tests/journeys/tools.py::measure      # runs measure(ui)

A journey is a Python file with functions that take one argument, the `UI` below. Targets are found by `objectName`
or by the text a user reads on them, and are pressed with `QTest` mouse and key events sent to the window, so a
button that does nothing fails the journey. Outcomes are asserted against the Store (`ui.store.get("stage")`,
`ui.js("Store.data.project.head")`) and against the engine itself (`ui.api("/projects/x")`, `ui.studio`).

The run uses the data folder in $FORM_DATA (the test suite gives each journey its own copy), its own window
settings, never the network, and - when $FORM_UITEST_AGENT names a script - a stand-in agent CLI, so no model runs.
Exit code 0 means every assertion held and the interface printed no QML warning.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

TEXT_PROPS = ("text", "tip", "title", "label", "placeholder", "k")


class UIError(AssertionError):
    pass


def prepare(cfg: dict) -> None:
    """Called before the engine starts: isolate window settings and swap in the stand-in agent when asked."""
    from PySide6.QtCore import QCoreApplication, QSettings
    QCoreApplication.setOrganizationName("FORM-uitest")
    QCoreApplication.setApplicationName("FORM-uitest")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tempfile.mkdtemp(prefix="form-uitest-settings-"))
    # QTest's click and key functions process events while this thread holds the interpreter lock. With Qt Quick's
    # threaded render loop the window then waits for the render thread, which waits for the lock to read the
    # Python-made geometry: a deadlock. Rendering on the main thread avoids it (the app itself is unaffected).
    os.environ.setdefault("QSG_RENDER_LOOP", "basic")
    if not os.environ.get("FORM_UITEST_FILES"):          # where "saved" files go instead of a native dialog
        os.environ["FORM_UITEST_FILES"] = tempfile.mkdtemp(prefix="form-uitest-files-")
    fake = os.environ.get("FORM_UITEST_AGENT", "")
    if fake:
        cfg["_adapters"] = {"fake": _fake_adapter(Path(fake), Path(cfg["data"]["dir"]))}
        if os.environ.get("FORM_UITEST_API_AGENTS") == "1":     # the API agents too (tests/journeys/agents.py)
            from ..agents.api import all_api_adapters
            cfg["_adapters"].update({a.id: a for a in all_api_adapters()})
        cfg["chat"] = dict(cfg.get("chat") or {}, enabled=True, agent="fake", model="default", effort="")


def _fake_adapter(script: Path, data: Path):
    from ..agents.base import Adapter
    from ..agents.claude import ClaudeParser

    class Fake(Adapter):
        """Runs a script that speaks Claude Code's stream-json (tests/fixtures/fake_agent.py)."""
        id, label, cli = "fake", "Test agent", "python"
        images, cost = True, True

        def executable(self, cfg):
            return sys.executable

        def models(self, cfg, exe):
            return [{"id": "default", "label": "Default", "note": ""}, {"id": "small", "label": "Small", "note": ""}]

        def command(self, run, exe):
            return [exe, str(script), str(data), run.session or "-", run.model, run.message]

        def run_env(self, run):            # the stand-in plays Form Studio's MCP server too: it answers ask_user itself
            d = (run.mcp.get("env") or {}).get("FORM_ASK_DIR")
            return {"FORM_ASK_DIR": d} if d else {}

        def parser(self):
            return ClaudeParser()

    return Fake()


class StoreProxy:
    """Reads the QML `Store` singleton. Values come back as plain Python (dict/list/str/number/bool/None)."""

    def __init__(self, ui: "UI"):
        self._ui = ui

    def get(self, name: str):
        return self._ui.js("Store." + name)

    prop = get

    def call(self, expr: str):
        """Run `Store.<expr>` for its effect, e.g. call('openSheet("slicer")'). Prefer real clicks; this is for setup."""
        return self._ui.run_js("Store." + expr)


class UI:
    def __init__(self, app, engine, win, studio, bridge, warnings: list, out_dir: Path):
        from PySide6.QtTest import QTest
        self.app, self.engine, self.win, self.studio, self.bridge = app, engine, win, studio, bridge
        self.base = f"http://{bridge.host}:{bridge.port}"
        self.files = Path(os.environ["FORM_UITEST_FILES"])          # native save dialogs write here
        self.warnings, self.out = warnings, out_dir
        self.store = StoreProxy(self)
        self.T = QTest
        self.timeout = float(os.environ.get("FORM_UITEST_TIMEOUT", "30"))
        self.log: list[str] = []

    # -- time ----------------------------------------------------------------
    def _pump(self, ms: int = 0):
        """Run the event loop for ms. Unlike QTest.qWait this lets go of the interpreter lock, so the engine's
        threads (HTTP server, jobs, geometry loading) keep running while the test waits."""
        from PySide6.QtCore import QEventLoop, QTimer
        loop = QEventLoop()
        QTimer.singleShot(max(0, int(ms)), loop.quit)
        loop.exec()

    def wait(self, ms: int = 50):
        self._pump(ms)

    def wait_until(self, cond, timeout: float | None = None, what: str = ""):
        """Pump the event loop until cond() is truthy. Returns its value; raises with `what` on timeout."""
        t0, last = time.time(), None
        limit = self.timeout if timeout is None else timeout
        while True:
            try:
                last = cond()
            except UIError:
                last = None
            if last:
                return last
            if time.time() - t0 > limit:
                raise UIError(f"timed out after {limit:.0f}s waiting for {what or getattr(cond, '__name__', 'condition')}")
            self._pump(25)

    def settle(self, ms: int = 250):
        """Let running animations finish (sheets enter in 180 ms)."""
        self._pump(ms)

    def idle(self, timeout: float | None = None):
        """Wait until no engine job is running and the project state has loaded."""
        self.wait_until(lambda: self.js("Store.job === '' && !Store.previewBusy") is True, timeout, "the engine to be idle")

    # -- JS ------------------------------------------------------------------
    def _expr(self, code: str):
        from PySide6.QtQml import QQmlEngine, QQmlExpression
        ex = QQmlExpression(QQmlEngine.contextForObject(self.win), self.win, code)
        v = ex.evaluate()
        if isinstance(v, tuple):          # PySide returns (value, valueIsUndefined)
            v = v[0]
        if ex.hasError():
            raise UIError(f"JS error in {code!r}: {ex.error().toString()}")
        return v

    def js(self, expr: str):
        """Evaluate a QML/JS expression in Main.qml's scope and return it as plain Python."""
        v = self._expr("(function(){ var __v = (" + expr + "); return __v === undefined ? 'null' : JSON.stringify(__v) })()")
        try:
            return json.loads(v) if isinstance(v, str) else v
        except ValueError:
            return v

    def run_js(self, code: str):
        self._expr(code)
        self._pump(0)

    # -- engine --------------------------------------------------------------
    def api(self, path: str, body=None):
        """GET (or POST when body is given) the engine API the app itself uses. Returns parsed JSON."""
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + "/api" + path, data=data, headers={"Content-Type": "application/json"} if data else {})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            raw = e.read()
        try:
            return json.loads(raw)
        except ValueError:
            return raw

    # -- files and the world outside the window ---------------------------------
    def pick_file(self, path):
        """The next native open dialog answers with this file (save dialogs answer with a path in ui.files)."""
        self.bridge._test_pick = str(path)

    def saved(self, name: str, timeout: float = 30) -> Path:
        """Wait for a file a save dialog wrote into ui.files; returns its path."""
        p = self.files / name
        self.wait_until(lambda: p.exists() and p.stat().st_size > 0, timeout, f"{name} to be saved")
        return p

    @property
    def outside(self) -> list:
        """What the app asked the desktop to open (Finder reveals, links, folders); recorded, not done."""
        return list(getattr(self.bridge, "outside", []))

    # -- finding -------------------------------------------------------------
    def _roots(self):
        return [self.win.contentItem()]

    def _walk(self, item):
        yield item
        for c in item.childItems():
            yield from self._walk(c)

    def _shown(self, item) -> bool:
        if not item.isVisible() or item.width() <= 0 or item.height() <= 0:
            return False
        p = item
        while p is not None:
            if p.opacity() < 0.02:
                return False
            p = p.parentItem()
        return True

    def _on_screen(self, item) -> bool:
        from PySide6.QtCore import QPointF
        c = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
        return 0 <= c.x() <= self.win.width() and 0 <= c.y() <= self.win.height()

    @staticmethod
    def _text_of(item) -> list[str]:
        out = []
        for p in TEXT_PROPS:
            v = item.property(p)
            if isinstance(v, str) and v:
                out.append(v)
        return out

    def find_all(self, name: str | None = None, text: str | None = None, within=None, exact: bool = True, shown: bool = True) -> list:
        roots = [within] if within is not None else self._roots()
        if isinstance(within, str):
            roots = [self.item(within)]
        hits = []
        for root in roots:
            for it in self._walk(root):
                if name is not None and it.objectName() != name:
                    continue
                if text is not None:
                    ts = self._text_of(it)
                    if not (text in ts if exact else any(text.lower() in t.lower() for t in ts)):
                        continue
                if shown and not self._shown(it):
                    continue
                hits.append(it)
        return hits

    def find(self, name: str | None = None, text: str | None = None, within=None, exact: bool = True, nth: int = 0):
        hits = self.find_all(name, text, within, exact)
        vis = [h for h in hits if self._on_screen(h)] or hits
        return vis[nth] if len(vis) > nth else None

    def item(self, name: str | None = None, text: str | None = None, within=None, exact: bool = True, nth: int = 0, timeout: float | None = None):
        """The visible item with this objectName / text; waits for it to appear."""
        what = f"an item named {name!r}" if name else f"an item reading {text!r}"
        return self.wait_until(lambda: self.find(name, text, within, exact, nth), 8 if timeout is None else timeout, what)

    def exists(self, name: str | None = None, text: str | None = None, within=None, exact: bool = True) -> bool:
        return self.find(name, text, within, exact) is not None

    def texts(self, within=None) -> list[str]:
        """Every visible string under `within` (or the window), in tree order."""
        root = self.item(within) if isinstance(within, str) else within
        out = []
        for it in self._walk(root or self.win.contentItem()):
            if self._shown(it):
                v = it.property("text")
                if isinstance(v, str) and v.strip():
                    out.append(v)
        return out

    def sees(self, text: str, within=None) -> bool:
        low = text.lower()
        return any(low in t.lower() for t in self.texts(within))

    def expect(self, text: str, within=None, timeout: float | None = None):
        self.wait_until(lambda: self.sees(text, within), 8 if timeout is None else timeout, f"the text {text!r} on screen")

    # -- pointer -------------------------------------------------------------
    def _pt(self, target, fx: float = 0.5, fy: float = 0.5):
        from PySide6.QtCore import QPoint, QPointF
        if isinstance(target, (tuple, list)):
            return QPoint(int(target[0]), int(target[1]))
        it = self.item(target) if isinstance(target, str) else target
        p = it.mapToScene(QPointF(it.width() * fx, it.height() * fy))
        return QPoint(int(round(p.x())), int(round(p.y())))

    def _btn(self, button: str):
        from PySide6.QtCore import Qt
        return {"left": Qt.MouseButton.LeftButton, "right": Qt.MouseButton.RightButton, "middle": Qt.MouseButton.MiddleButton}[button]

    def _mods(self, mods: str = ""):
        from PySide6.QtCore import Qt
        m = Qt.KeyboardModifier.NoModifier
        for part in filter(None, mods.split("+")):
            m |= {"ctrl": Qt.KeyboardModifier.ControlModifier, "shift": Qt.KeyboardModifier.ShiftModifier,
                  "alt": Qt.KeyboardModifier.AltModifier, "meta": Qt.KeyboardModifier.MetaModifier}[part.lower()]
        return m

    def _flick(self, item):
        p = item.parentItem()
        while p is not None:
            if p.property("contentY") is not None and p.property("contentHeight") is not None and p.property("interactive") is not None:
                return p
            p = p.parentItem()
        return None

    def scroll_to(self, target, fy: float = 0.5):
        """Bring an item inside a scrolling panel into view with wheel events, the way a hand would."""
        from PySide6.QtCore import QPointF
        it = self.item(target) if isinstance(target, str) else target
        fl = self._flick(it)
        if fl is None:
            return
        for _ in range(60):
            y = it.mapToItem(fl, QPointF(0, it.height() * fy)).y()
            if 60 <= y <= fl.height() - 90:
                for _ in range(80):                        # a press on a view that is still gliding only stops it
                    if not fl.property("moving") and not fl.property("flicking"):
                        break
                    self._pump(25)
                return
            before = fl.property("contentY")
            self.wheel(fl, -240 if y > fl.height() - 90 else 240)
            self._pump(30)
            if abs(fl.property("contentY") - before) < 0.5:        # at the end, or the wheel did nothing: place it
                want = before + (y - fl.height() / 2)
                top = max(0.0, float(fl.property("contentHeight")) - fl.height())
                fl.setProperty("contentY", max(0.0, min(top, want)))
                self._pump(30)
                return

    def hover(self, target, fx: float = 0.5, fy: float = 0.5):
        if not isinstance(target, (tuple, list)):
            self.scroll_to(target, fy)
        p = self._pt(target, fx, fy)
        self.T.mouseMove(self.win, p)
        self._pump(15)
        return p

    def click(self, target, fx: float = 0.5, fy: float = 0.5, button: str = "left", mods: str = ""):
        """Press and release on an item (by objectName, or the item itself, or (x, y) in the window)."""
        label = target if isinstance(target, (str, tuple)) else (target.objectName() or (self._text_of(target) or [target.metaObject().className()])[0])
        p = self.hover(target, fx, fy)
        self.log.append(f"click {label} @ {p.x()},{p.y()}")
        self.T.mouseClick(self.win, self._btn(button), self._mods(mods), p)
        self._pump(20)

    def click_text(self, text: str, within=None, exact: bool = True, nth: int = 0, button: str = "left"):
        self.click(self.item(text=text, within=within, exact=exact, nth=nth), button=button)

    def right_click(self, target, fx: float = 0.5, fy: float = 0.5):
        self.click(target, fx, fy, button="right")

    def dclick(self, target, fx: float = 0.5, fy: float = 0.5):
        p = self.hover(target, fx, fy)
        self.T.mouseClick(self.win, self._btn("left"), self._mods(), p)
        self.T.mouseDClick(self.win, self._btn("left"), self._mods(), p)
        self._pump(20)

    def drag(self, target, to, fx: float = 0.5, fy: float = 0.5, steps: int = 8, button: str = "left", hold: bool = False):
        """Press on `target` at (fx, fy), move to `to` ((dx, dy) relative pixels, or an item), release."""
        from PySide6.QtCore import QPoint
        a = self._pt(target, fx, fy)
        b = QPoint(a.x() + int(to[0]), a.y() + int(to[1])) if isinstance(to, (tuple, list)) else self._pt(to)
        self.T.mouseMove(self.win, a)
        self.T.mousePress(self.win, self._btn(button), self._mods(), a)
        for i in range(1, steps + 1):
            self.T.mouseMove(self.win, QPoint(a.x() + (b.x() - a.x()) * i // steps, a.y() + (b.y() - a.y()) * i // steps))
            self._pump(12)
        if not hold:
            self.T.mouseRelease(self.win, self._btn(button), self._mods(), b)
        self._pump(20)
        return b

    def stroke(self, target, path, fx: float = 0.5, fy: float = 0.5, mods: str = "", steps: int = 4):
        """Press on `target` at (fx, fy), move through `path` ((dx, dy) pixels relative to the press), release: a brush
        stroke or a lasso drawn by hand, with modifiers (``mods="shift"``) held throughout."""
        from PySide6.QtCore import QPoint
        a = self._pt(target, fx, fy)
        m = self._mods(mods)
        self.T.mouseMove(self.win, a)
        self.T.mousePress(self.win, self._btn("left"), m, a)
        prev = a
        for dx, dy in path:
            q = QPoint(a.x() + int(dx), a.y() + int(dy))
            for i in range(1, steps + 1):
                self.T.mouseMove(self.win, QPoint(prev.x() + (q.x() - prev.x()) * i // steps, prev.y() + (q.y() - prev.y()) * i // steps))
                self._pump(8)
            prev = q
        self.T.mouseRelease(self.win, self._btn("left"), m, prev)
        self._pump(20)
        return prev

    def release(self, at, button: str = "left"):
        self.T.mouseRelease(self.win, self._btn(button), self._mods(), self._pt(at))
        self._pump(20)

    def wheel(self, target, dy: int = -120, fx: float = 0.5, fy: float = 0.5):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent
        p = self._pt(target, fx, fy)
        g = self.win.mapToGlobal(p)
        ev = QWheelEvent(QPointF(p), QPointF(g), QPoint(0, 0), QPoint(0, dy), Qt.MouseButton.NoButton,
                         Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        self.app.sendEvent(self.win, ev)
        self._pump(20)

    # -- keyboard ------------------------------------------------------------
    def key(self, seq: str, n: int = 1):
        """Press a key or chord written the Qt way: "Ctrl+K", "Escape", "Tab", "Shift+Tab", "V", "Ctrl+Return"."""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeySequence
        ks = QKeySequence(seq)
        if ks.count() != 1:
            raise UIError(f"not a single key chord: {seq!r}")
        kc = ks[0]
        k, mods = kc.key(), kc.keyboardModifiers()
        if seq.lower().endswith("shift+tab"):
            k = Qt.Key.Key_Backtab
        for _ in range(n):
            self.T.keyClick(self.win, k, mods)
            self._pump(20)
        self.log.append(f"key {seq}" + (f" ×{n}" if n > 1 else ""))

    def type(self, text: str):
        """Type into whatever has the keyboard."""
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent
        for ch in text:
            code = ord(ch.upper()) if ch.isascii() and ch.isprintable() else 0
            mods = Qt.KeyboardModifier.ShiftModifier if ch.isupper() else Qt.KeyboardModifier.NoModifier
            for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                self.app.sendEvent(self.win, QKeyEvent(kind, code, mods, ch))
            self._pump(2)
        self._pump(20)
        self.log.append(f"type {text!r}")

    def clear(self):
        """Select all in the focused field and delete it."""
        self.key("Ctrl+A")
        self.key("Backspace")

    def fill(self, target, text: str, enter: bool = False):
        """Click a field, replace its contents, optionally press Return."""
        self.click(target)
        self.clear()
        self.type(text)
        if enter:
            self.key("Return")

    def focus_item(self):
        return self.win.activeFocusItem()

    def focus_inside(self, ancestor) -> bool:
        anc = self.item(ancestor) if isinstance(ancestor, str) else ancestor
        it = self.win.activeFocusItem()
        while it is not None:
            if it is anc or it == anc:
                return True
            it = it.parentItem()
        return False

    # -- window --------------------------------------------------------------
    def resize(self, w: int, h: int):
        self.win.resize(w, h)
        self.wait_until(lambda: self.win.width() == w and self.win.height() == h, 5, f"the window to be {w}x{h}")
        self.settle(350)

    def shot(self, name: str) -> Path:
        self.out.mkdir(parents=True, exist_ok=True)
        p = self.out / (name if name.endswith(".png") else name + ".png")
        self._pump(60)
        self.win.grabWindow().save(str(p))
        return p

    # -- assertions ----------------------------------------------------------
    def check(self, ok, msg: str = ""):
        if not ok:
            raise UIError(msg or "check failed")

    def eq(self, a, b, msg: str = ""):
        if a != b:
            raise UIError(f"{msg + ': ' if msg else ''}{a!r} != {b!r}")

    def no_warnings(self):
        # a sheet closed while a view was still creating its delegates (slow software rendering): teardown, nothing shown
        teardown = ("Object or context destroyed during incubation", "Cannot create delegate")
        bad = [w for w in self.warnings if "Binding loop" not in w and not any(t in w for t in teardown)]
        if bad:
            raise UIError("QML warnings:\n  " + "\n  ".join(bad))


def _load(script: str):
    path, _, fn = script.partition("::")
    spec = importlib.util.spec_from_file_location("form_journey_" + Path(path).stem, path)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(Path(path).resolve().parent))
    spec.loader.exec_module(mod)
    names = [fn] if fn else (["run"] if hasattr(mod, "run") else [n for n in vars(mod) if n.startswith("journey_")])
    return [(n, getattr(mod, n)) for n in names]


def run_script(app, engine, win, studio, bridge, script: str, warnings: list, finish) -> None:
    """Run the journey functions of `script`, then quit the app with 0 (all passed) or 1."""
    import faulthandler
    import signal
    # a journey that blocks the event loop cannot time itself out: print every thread's stack and leave
    faulthandler.dump_traceback_later(float(os.environ.get("FORM_UITEST_WATCHDOG", "900")), exit=True)
    if hasattr(signal, "SIGUSR1"):
        faulthandler.register(signal.SIGUSR1, all_threads=True)
    out = Path(os.environ.get("FORM_UITEST_OUT", ".dev/uitest"))
    ui = UI(app, engine, win, studio, bridge, warnings, out)
    rc = 0
    try:
        win.requestActivate()
        ui.wait_until(lambda: ui.js("Store.screen") != "boot", 60, "the app to start")
        for name, fn in _load(script):
            t0 = time.time()
            try:
                fn(ui)
                if os.environ.get("FORM_UITEST_LAX") != "1":
                    ui.no_warnings()
                print(f"PASS {name} ({time.time() - t0:.1f}s)", flush=True)
            except Exception:
                rc = 1
                try:
                    shot = ui.shot("fail-" + Path(script.partition('::')[0]).stem + "-" + name)
                except Exception:
                    shot = None
                print(f"FAIL {name} ({time.time() - t0:.1f}s)" + (f"  screenshot: {shot}" if shot else ""), flush=True)
                traceback.print_exc()
                print("  last actions: " + " | ".join(ui.log[-8:]), file=sys.stderr, flush=True)
                if os.environ.get("FORM_UITEST_DUMP") == "1":
                    try:
                        print("  on screen: " + " ¦ ".join(t.replace("\n", " ")[:60] for t in ui.texts()), file=sys.stderr, flush=True)
                    except Exception:
                        pass
                break
    except Exception:
        rc = 1
        traceback.print_exc()
    finish(rc)
